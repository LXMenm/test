from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from config import DIAGNOSIS_CONFIDENCE_THRESHOLD
from diagnosis_model import get_diagnosis_engine
from event_store import (
    append_event,
    list_events,
    stats_by_disease,
    timeseries,
    geo_points,
    list_events_range,
    stats_by_disease_range,
    timeseries_range,
    geo_points_range,
)
from knowledge_base import get_kb_manager
from personalization.profile_models import FarmerProfile, TreatmentConstraint
from personalization.profile_rules import filter_treatment_by_constraints
from personalization.profile_store import get_profile_path, load_profile, list_profile_ids
from state import create_initial_state
from trace_store import list_trace_events
from workflow import build_graph


app = FastAPI(title="Tomato Diagnosis API", version="1.0.0")
kb = get_kb_manager()
UPLOAD_DIR = Path(".cache/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WEB_DIR = Path("web")
WEB_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_MB = 8
TOP_MARGIN = 0.15


class Top3Item(BaseModel):
    disease: str
    prob: float
    prob_pct: float


class ImageResult(BaseModel):
    disease: str
    confidence: float
    confidence_pct: float
    top3: list[Top3Item]


class RuleResult(BaseModel):
    rule_disease: Optional[str]
    rule_confidence: float
    rule_confidence_pct: float
    rule_description: str


class TreatmentPlan(BaseModel):
    plan: str
    prevention: str


class DiagnoseResponse(BaseModel):
    image_id: str
    image_url: str
    image_result: ImageResult
    fallback_used: bool
    fallback_reason: Optional[list[str]]
    rule_result: Optional[RuleResult]
    final_disease: str
    treatment: Optional[TreatmentPlan]
    personalization_applied: bool
    farmer_id: Optional[str]
    filtered: bool
    filtered_reasons: list[str]
    trace_id: str

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def cleanup_old_uploads(max_age_hours: int = 24) -> None:
    now_ts = __import__("time").time()
    max_age_seconds = max_age_hours * 3600
    for path in UPLOAD_DIR.glob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            if now_ts - path.stat().st_mtime > max_age_seconds:
                path.unlink(missing_ok=True)
        except Exception:
            continue


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/uploads/{image_id}")
def get_uploaded_image(image_id: str) -> FileResponse:
    suffix = Path(image_id).suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="不支持的图片后缀")

    target = (UPLOAD_DIR / image_id).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if not str(target).startswith(str(upload_root)):
        raise HTTPException(status_code=400, detail="非法文件路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")

    return FileResponse(path=target)


def apply_personalization_to_treatment(
    *,
    constraints: TreatmentConstraint,
    treatment: TreatmentPlan | None,
    disease: str,
) -> tuple[TreatmentPlan | None, bool, list[str]]:
    if not treatment:
        return None, False, []

    original_plan = treatment.plan or ""
    original_prevention = treatment.prevention or ""
    filtered_plan, dropped_plan = filter_treatment_by_constraints(original_plan, constraints)
    filtered_prevention, dropped_prevention = filter_treatment_by_constraints(
        original_prevention, constraints
    )

    reasons: list[str] = []
    banned_hits: list[str] = []
    combined = f"{original_plan}\n{original_prevention}".lower()
    for ingredient in constraints.banned_ingredients:
        if ingredient and ingredient.lower() in combined:
            banned_hits.append(ingredient)
    if banned_hits:
        reasons.append(f"包含禁用成分：{', '.join(sorted(set(banned_hits)))}")
    if constraints.prefer_organic:
        reasons.append("有机偏好已应用")
        filtered_plan = f"（有机偏好）优先选择生物防治/低残留药剂。\n{filtered_plan}".strip()
    if constraints.harvest_window_days:
        reasons.append(f"采收期约束：{constraints.harvest_window_days}天")

    filtered = bool(
        reasons
        or dropped_plan
        or dropped_prevention
        or filtered_plan != original_plan
        or filtered_prevention != original_prevention
    )

    filtered_treatment = TreatmentPlan(
        plan=filtered_plan or original_plan,
        prevention=filtered_prevention or original_prevention,
    )
    return filtered_treatment, filtered, reasons


def load_profile_payload(farmer_id: str) -> tuple[dict | None, TreatmentConstraint | None]:
    path = get_profile_path(farmer_id)
    if not path.exists():
        return None, None
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None, None

    profile = load_profile(farmer_id)
    if profile:
        return payload, profile.constraints

    constraints_data = payload.get("constraints") if isinstance(payload, dict) else None
    try:
        constraints = TreatmentConstraint.model_validate(constraints_data or {})
    except Exception:
        constraints = TreatmentConstraint()
    return payload, constraints


def build_trace_query(
    *,
    crop_type: str,
    symptoms_list: list[str],
    growth_stage: str | None,
    image_path: str,
) -> str:
    parts = []
    if crop_type:
        parts.append(f"作物类型：{crop_type}")
    if growth_stage:
        parts.append(f"生长阶段：{growth_stage}")
    if symptoms_list:
        parts.append(f"症状：{', '.join(symptoms_list)}")
    parts.append(f"图片路径：{image_path}")
    return "，".join(parts)


@app.post("/api/diagnose-image", response_model=DiagnoseResponse)
async def diagnose_image(
    file: UploadFile = File(...),
    crop_type: str = Form("番茄"),
    symptoms: str | None = Form(None),
    growth_stage: str | None = Form(None),
    farmer_id: str | None = Form(None),
    base_id: str | None = Form(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
) -> DiagnoseResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    suffix = Path(file.filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix not in IMAGE_EXTS and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片文件上传")

    unique_name = f"{uuid.uuid4().hex}{suffix or '.jpg'}"
    saved_path = UPLOAD_DIR / unique_name

    try:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"上传文件超过{MAX_UPLOAD_MB}MB限制")

        try:
            Image.open(BytesIO(data)).verify()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"上传文件不是有效图片: {exc}") from exc

        saved_path.write_bytes(data)
        cleanup_old_uploads()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取或保存图片失败: {exc}") from exc

    engine = get_diagnosis_engine()
    disease, conf, probs = engine.diagnose_from_image(str(saved_path))
    disease = disease or "未知病害"
    conf = float(conf or 0.0)

    if disease == "模型未加载":
        raise HTTPException(status_code=500, detail="模型未加载，请先配置并加载模型")
    if probs is None:
        probs = {}

    sorted_probs = sorted(probs.items(), key=lambda x: x[1], reverse=True)
    top3_pairs = sorted_probs[:3]
    top3 = [
        {
            "disease": name,
            "prob": float(prob),
            "prob_pct": round(float(prob) * 100, 2),
        }
        for name, prob in top3_pairs
    ]

    top1_conf = float(top3_pairs[0][1]) if top3_pairs else conf
    top2_conf = float(top3_pairs[1][1]) if len(top3_pairs) > 1 else None

    fallback_reasons: list[str] = []
    if top1_conf < DIAGNOSIS_CONFIDENCE_THRESHOLD:
        fallback_reasons.append("low_confidence")
    if top2_conf is not None and (top1_conf - top2_conf) < TOP_MARGIN:
        fallback_reasons.append("low_margin")

    symptoms_list = [s.strip() for s in (symptoms or "").split(",") if s.strip()]
    fallback_condition = bool(fallback_reasons)

    fallback_used = False
    rule_result: RuleResult | None = None

    if fallback_condition and symptoms_list:
        try:
            rule_disease, rule_confidence, rule_description = engine.diagnose_from_symptoms(
                crop_type=crop_type,
                symptoms=symptoms_list,
                growth_stage=growth_stage,
            )
            fallback_used = True
            rule_result = RuleResult(
                rule_disease=rule_disease,
                rule_confidence=float(rule_confidence),
                rule_confidence_pct=round(float(rule_confidence) * 100, 2),
                rule_description=rule_description,
            )
        except Exception as exc:
            rule_result = RuleResult(
                rule_disease=None,
                rule_confidence=0.0,
                rule_confidence_pct=0.0,
                rule_description=f"症状回退诊断失败: {exc}",
            )
            fallback_used = True

    final_disease = disease
    if fallback_used and rule_result and rule_result.rule_disease:
        final_disease = rule_result.rule_disease

    treatment: TreatmentPlan | None = None
    if final_disease:
        plan = kb.get_treatment_plan(final_disease)
        if isinstance(plan, dict) and "treatment" in plan and "prevention" in plan:
            treatment = TreatmentPlan(
                plan=plan["treatment"],
                prevention=plan["prevention"],
            )

    personalization_applied = False
    filtered = False
    filtered_reasons: list[str] = []
    if farmer_id:
        _, constraints = load_profile_payload(farmer_id)
        if constraints:
            personalization_applied = True
            treatment, filtered, filtered_reasons = apply_personalization_to_treatment(
                constraints=constraints,
                treatment=treatment,
                disease=final_disease,
            )

    image_result_dict = {
        "disease": disease,
        "confidence": conf,
        "confidence_pct": round(conf * 100, 2),
        "top3": top3,
    }
    rule_result_dict = rule_result.model_dump() if rule_result else None
    treatment_or_none = treatment.model_dump() if treatment else None
    image_url = f"/uploads/{unique_name}"

    trace_id = uuid.uuid4().hex
    final_state = None
    try:
        query_text = build_trace_query(
            crop_type=crop_type,
            symptoms_list=symptoms_list,
            growth_stage=growth_stage,
            image_path=str(saved_path),
        )
        initial_state = create_initial_state(query_text, farmer_id=farmer_id, base_id=base_id)
        graph = build_graph()
        final_state = graph.invoke(initial_state)
        trace_id = final_state.get("trace_id", trace_id)
    except Exception as exc:
        print(f"Warning: failed to build trace events: {exc}")

    if final_state and final_state.get("final_disease"):
        final_disease = final_state.get("final_disease") or final_disease
        if final_disease:
            plan = kb.get_treatment_plan(final_disease)
            if isinstance(plan, dict) and "treatment" in plan and "prevention" in plan:
                treatment = TreatmentPlan(
                    plan=plan["treatment"],
                    prevention=plan["prevention"],
                )
            if farmer_id:
                _, constraints = load_profile_payload(farmer_id)
                if constraints:
                    personalization_applied = True
                    treatment, filtered, filtered_reasons = apply_personalization_to_treatment(
                        constraints=constraints,
                        treatment=treatment,
                        disease=final_disease,
                    )

    event = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "trace_id": trace_id,
        "crop_type": crop_type,
        "symptoms": symptoms_list,
        "image_id": unique_name,
        "image_url": image_url,
        "image_result": image_result_dict,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reasons or None,
        "rule_result": rule_result_dict,
        "final_disease": final_state.get("final_disease") if final_state else final_disease,
        "treatment": treatment_or_none,
        "meta": {
            "farmer_id": farmer_id,
            "base_id": base_id,
            "lat": lat,
            "lon": lon,
            "personalization_applied": personalization_applied,
            "filtered": filtered,
            "filtered_reasons": filtered_reasons,
        },
    }
    try:
        append_event(event)
    except Exception as exc:
        print(f"Warning: failed to append event: {exc}")

    return DiagnoseResponse(
        image_id=unique_name,
        image_url=image_url,
        image_result=ImageResult(**image_result_dict),
        fallback_used=fallback_used,
        fallback_reason=fallback_reasons or None,
        rule_result=rule_result,
        final_disease=final_disease,
        treatment=treatment,
        personalization_applied=personalization_applied,
        farmer_id=farmer_id,
        filtered=filtered,
        filtered_reasons=filtered_reasons,
        trace_id=trace_id,
    )


@app.get("/api/profiles")
def list_profiles() -> dict[str, list[dict[str, str]]]:
    profiles = []
    for farmer_id in list_profile_ids():
        path = get_profile_path(farmer_id)
        profiles.append({"id": farmer_id, "path": str(path)})
    return {"profiles": profiles}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _generate_farmer_id() -> str | None:
    existing_ids = set()
    for farmer_id in list_profile_ids():
        match = re.match(r"^F(\d{4})$", farmer_id)
        if match:
            existing_ids.add(int(match.group(1)))
    for index in range(1, 1001):
        if index not in existing_ids:
            return f"F{index:04d}"
    return None


@app.post("/api/profiles")
def create_profile(payload: dict = Body(...)) -> dict[str, bool | str]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="档案内容非法")
    farmer_id = payload.get("farmer_id")
    if not farmer_id:
        farmer_id = _generate_farmer_id()
        if not farmer_id:
            raise HTTPException(status_code=409, detail="农户ID已满")
    path = get_profile_path(farmer_id)
    if path.exists():
        raise HTTPException(status_code=409, detail="农户ID已存在")

    profile = FarmerProfile(farmer_id=farmer_id, name=payload.get("name"))
    if "confirm_when_low_confidence" in payload:
        profile.confirm_when_low_confidence = bool(payload.get("confirm_when_low_confidence"))
    if "constraints" in payload and isinstance(payload.get("constraints"), dict):
        try:
            profile.constraints = TreatmentConstraint.model_validate(payload["constraints"])
        except Exception:
            profile.constraints = TreatmentConstraint()
    profile.ensure_timestamp()
    profile.updated_at = _utc_now_iso()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(profile.model_dump(), f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建档案失败: {exc}") from exc
    return {"ok": True, "id": farmer_id}


@app.get("/api/profiles/{farmer_id}")
def get_profile(farmer_id: str) -> dict:
    path = get_profile_path(farmer_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="档案不存在")
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"档案内容非法: {exc}") from exc


@app.post("/api/profiles/{farmer_id}")
def save_profile(farmer_id: str, payload: dict = Body(...)) -> dict[str, bool]:
    path = get_profile_path(farmer_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="档案内容非法")
    payload["updated_at"] = _utc_now_iso()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存档案失败: {exc}") from exc
    return {"ok": True}


@app.delete("/api/profiles/{farmer_id}")
def delete_profile(farmer_id: str) -> dict[str, bool]:
    path = get_profile_path(farmer_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="档案不存在")
    try:
        path.unlink()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除档案失败: {exc}") from exc
    return {"ok": True}


@app.get("/api/events")
def get_events(start: str | None = None, end: str | None = None, limit: int = 50) -> list[dict]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return list_events_range(start, end, limit)
    return list_events(limit)


@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str) -> dict[str, object]:
    events = list_trace_events(trace_id)
    return {"trace_id": trace_id, "events": events}


def validate_date_str(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


@app.get("/api/stats/disease")
def get_disease_stats(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
) -> dict[str, int]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return stats_by_disease_range(start, end)
    safe_days = max(1, min(3650, int(days)))
    return stats_by_disease(safe_days)


@app.get("/api/stats/timeseries")
def get_timeseries(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
) -> list[dict]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return timeseries_range(start, end)
    safe_days = max(1, min(3650, int(days)))
    return timeseries(safe_days)


@app.get("/api/stats/geo")
def get_geo_stats(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
) -> list[dict]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return geo_points_range(start, end)
    safe_days = max(1, min(3650, int(days)))
    return geo_points(safe_days)


@app.get("/dashboard")
def get_dashboard() -> FileResponse:
    dashboard_path = WEB_DIR / "dashboard.html"
    if not dashboard_path.exists():
        raise HTTPException(status_code=404, detail="dashboard.html 不存在")
    return FileResponse(dashboard_path)


@app.get("/profiles")
def get_profiles_page() -> FileResponse:
    profiles_path = WEB_DIR / "profiles.html"
    if not profiles_path.exists():
        raise HTTPException(status_code=404, detail="profiles.html 不存在")
    return FileResponse(profiles_path)


@app.get("/kb")
def get_kb_page() -> FileResponse:
    kb_path = WEB_DIR / "kb.html"
    if not kb_path.exists():
        raise HTTPException(status_code=404, detail="kb.html 不存在")
    return FileResponse(kb_path)


@app.get("/api/kb/diseases")
def list_kb_diseases() -> dict:
    return {"items": kb.list_diseases()}


@app.post("/api/kb/diseases")
def create_kb_disease(payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    if not name or not description:
        raise HTTPException(status_code=400, detail="病害名称与描述不能为空")
    existing = {item["name"] for item in kb.list_diseases()}
    if name in existing:
        raise HTTPException(status_code=409, detail="病害已存在，请使用编辑")
    kb.upsert_disease(name, description)
    return {"ok": True}


@app.put("/api/kb/diseases/{name}")
def update_kb_disease(name: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="病害描述不能为空")
    existing = {item["name"] for item in kb.list_diseases()}
    if name not in existing:
        raise HTTPException(status_code=404, detail="病害不存在")
    kb.upsert_disease(name, description)
    return {"ok": True}


@app.delete("/api/kb/diseases")
def delete_kb_diseases(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    names = payload.get("names")
    if not isinstance(names, list) or not names:
        raise HTTPException(status_code=400, detail="病害列表不能为空")
    result = kb.delete_diseases([str(item).strip() for item in names if str(item).strip()])
    return {"ok": True, **result}


@app.get("/api/kb/treatments")
def list_kb_treatments() -> dict:
    return {"items": kb.list_treatments()}


@app.post("/api/kb/treatments")
def create_kb_treatments(payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    disease = (payload.get("disease") or "").strip()
    treatment = (payload.get("treatment") or "").strip()
    prevention = (payload.get("prevention") or "").strip()
    if not disease or not treatment or not prevention:
        raise HTTPException(status_code=400, detail="病害、治疗与预防不能为空")
    existing = {item["disease"] for item in kb.list_treatments()}
    if disease in existing:
        raise HTTPException(status_code=409, detail="治疗方案已存在，请使用编辑")
    kb.upsert_treatment_plan(disease, treatment, prevention)
    return {"ok": True}


@app.put("/api/kb/treatments/{disease}")
def update_kb_treatments(disease: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    treatment = (payload.get("treatment") or "").strip()
    prevention = (payload.get("prevention") or "").strip()
    if not treatment or not prevention:
        raise HTTPException(status_code=400, detail="治疗与预防不能为空")
    existing = {item["disease"] for item in kb.list_treatments()}
    if disease not in existing:
        raise HTTPException(status_code=404, detail="治疗方案不存在")
    kb.upsert_treatment_plan(disease, treatment, prevention)
    return {"ok": True}


@app.delete("/api/kb/treatments")
def delete_kb_treatments(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    diseases = payload.get("diseases")
    if not isinstance(diseases, list) or not diseases:
        raise HTTPException(status_code=400, detail="病害列表不能为空")
    deleted = kb.delete_treatments([str(item).strip() for item in diseases if str(item).strip()])
    return {"ok": True, "deleted": deleted}


@app.get("/api/kb/rules")
def list_kb_rules(crop_type: str | None = None) -> dict:
    return {"items": kb.list_rules(crop_type)}


@app.post("/api/kb/rules")
def create_kb_rule(payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    crop_type = (payload.get("crop_type") or "").strip() or "番茄"
    symptoms = payload.get("symptoms")
    disease = (payload.get("disease") or "").strip()
    evidence = (payload.get("evidence") or "").strip()
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="置信度必须为数字") from None
    if confidence < 0 or confidence > 1:
        raise HTTPException(status_code=400, detail="置信度需在 0~1 之间")
    if not isinstance(symptoms, list) or not symptoms:
        raise HTTPException(status_code=400, detail="症状不能为空")
    symptoms_list = [str(item).strip() for item in symptoms if str(item).strip()]
    if not symptoms_list or not disease:
        raise HTTPException(status_code=400, detail="症状与病害不能为空")
    rule_id = kb.add_rule(crop_type, symptoms_list, disease, confidence, evidence)
    return {"ok": True, "rule_id": rule_id}


@app.delete("/api/kb/rules")
def delete_kb_rules(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    rule_ids = payload.get("rule_ids")
    if not isinstance(rule_ids, list) or not rule_ids:
        raise HTTPException(status_code=400, detail="规则列表不能为空")
    deleted = kb.delete_rules([str(item).strip() for item in rule_ids if str(item).strip()])
    return {"ok": True, "deleted": deleted}


@app.put("/api/kb/rules/{rule_id}")
def update_kb_rule(rule_id: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    crop_type = (payload.get("crop_type") or "").strip() or "番茄"
    symptoms = payload.get("symptoms")
    disease = (payload.get("disease") or "").strip()
    evidence = (payload.get("evidence") or "").strip()
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="置信度必须为数字") from None
    if confidence < 0 or confidence > 1:
        raise HTTPException(status_code=400, detail="置信度需在 0~1 之间")
    if not isinstance(symptoms, list) or not symptoms:
        raise HTTPException(status_code=400, detail="症状不能为空")
    symptoms_list = [str(item).strip() for item in symptoms if str(item).strip()]
    if not symptoms_list or not disease:
        raise HTTPException(status_code=400, detail="症状与病害不能为空")
    if not kb.update_rule(rule_id, crop_type, symptoms_list, disease, confidence, evidence):
        raise HTTPException(status_code=404, detail="规则不存在")
    return {"ok": True}


@app.get("/api/kb/symptom-map")
def list_kb_symptom_map() -> dict:
    return {"items": kb.list_symptom_map()}


@app.post("/api/kb/symptom-map")
def create_kb_symptom_map(payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    symptom = (payload.get("symptom") or "").strip()
    diseases = payload.get("diseases")
    if not symptom or not isinstance(diseases, list) or not diseases:
        raise HTTPException(status_code=400, detail="症状与病害不能为空")
    disease_list = [str(item).strip() for item in diseases if str(item).strip()]
    if not disease_list:
        raise HTTPException(status_code=400, detail="病害不能为空")
    existing = {item["symptom"] for item in kb.list_symptom_map()}
    if symptom in existing:
        raise HTTPException(status_code=409, detail="症状映射已存在，请使用编辑")
    kb.upsert_symptom_mapping(symptom, disease_list)
    return {"ok": True}


@app.put("/api/kb/symptom-map/{symptom}")
def update_kb_symptom_map(symptom: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    diseases = payload.get("diseases")
    if not isinstance(diseases, list) or not diseases:
        raise HTTPException(status_code=400, detail="病害不能为空")
    existing = {item["symptom"] for item in kb.list_symptom_map()}
    if symptom not in existing:
        raise HTTPException(status_code=404, detail="症状映射不存在")
    disease_list = [str(item).strip() for item in diseases if str(item).strip()]
    if not disease_list:
        raise HTTPException(status_code=400, detail="病害不能为空")
    kb.upsert_symptom_mapping(symptom, disease_list)
    return {"ok": True}


@app.delete("/api/kb/symptom-map")
def delete_kb_symptom_map(payload: dict = Body(...)) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    symptoms = payload.get("symptoms")
    if not isinstance(symptoms, list) or not symptoms:
        raise HTTPException(status_code=400, detail="症状列表不能为空")
    deleted = kb.delete_symptom_map_entries([str(item).strip() for item in symptoms if str(item).strip()])
    return {"ok": True, "deleted": deleted}


if __name__ == "__main__":
    # 启动示例：uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    pass
