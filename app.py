from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import traceback
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from config import DIAGNOSIS_CONFIDENCE_THRESHOLD, DIAGNOSIS_ALLOW_TORCH
from diagnosis_model import get_diagnosis_engine
import diagnosis_model as diagnosis_model_module
import agents as agents_module
import knowledge_base.kb_manager as kb_manager_module
from agents import append_trace, diagnosis_agent, kb_retrieval_agent, treatment_agent, verification_agent, supervisor_agent
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
    model_usage_range,
)
from knowledge_base import get_kb_manager
from personalization import profile_rules
from personalization.profile_constants import estimate_harvest_window_days, growth_stage_label, normalize_growth_stage
from personalization.profile_models import BaseProfile, FarmerProfile, TreatmentConstraint
from personalization.profile_context import build_personalization_context, build_personalization_flags
from personalization.profile_store import get_profile_path, load_profile, list_profile_ids, save_profile as persist_profile
from personalization.utils import dedupe_reasons, compute_personalization_applied, normalize_follow_up_questions
from state import create_initial_state
from trace_store import list_trace_events, subscribe as subscribe_trace, unsubscribe as unsubscribe_trace, emit_trace_event
from model_registry import list_models, resolve_model
from workflow import build_graph
from trace_catalog import AGENTS_CATALOG, NODE_TO_AGENT


app = FastAPI(title="Tomato Diagnosis API", version="1.0.0")
kb = get_kb_manager()
UPLOAD_DIR = Path(".cache/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FRONTEND_DIR = Path("app/dist")
LEGACY_WEB_DIR = Path("web")
MAX_UPLOAD_MB = 8
TOP_MARGIN = 0.15


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一兜底：确保 API 异常返回 JSON，便于前端透传错误。"""
    tb = traceback.format_exc()
    traceback.print_exc()
    detail = str(exc) or exc.__class__.__name__
    payload = {
        "detail": detail,
        "error": exc.__class__.__name__,
    }
    if request.url.path == "/api/diagnose-image":
        payload["traceback"] = tb
    return JSONResponse(status_code=500, content=payload)


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
    treatment: Optional[TreatmentPlan] = None
    personalization_applied: bool = False
    farmer_id: Optional[str] = None
    risk_tags: list[str] | None = None
    risk_items: list[dict[str, Any]] | None = None
    risk_summary: str | None = None
    risk_updated_at: str | None = None
    filtered: bool
    filtered_reasons: list[str]
    filtered_components: list[str]
    filtered_actions: list[str] = []
    personalization_reasons: list[str]
    follow_up_questions: list[str] = []
    historical_follow_up_questions: list[str] = []
    missing_profile_fields: list[str] = []
    profile_farm_scale: str | None = None
    profile_pesticide_access_level: str | None = None
    profile_equipment: list[str] = []
    profile_cultivation_mode: str | None = None
    selected_branch: str | None = None
    llm_failed: bool = False
    trace_id: str
    need_confirm: bool | None = None
    final_confidence: float | None = None
    final_source: str | None = None
    model_id: str | None = None
    model_display_name: str | None = None
    model_backend: str | None = None
    resolved_model_path: str | None = None
    model_fallback_reason: list[str] | None = None
    workflow_degraded: bool = False
    degraded_reason: str | None = None
    text_top3: list[tuple[str, float]] = []
    fusion_top3: list[tuple[str, float]] = []
    diagnosis_evidence: dict[str, Any] | None = None
    modality_conflict_flag: bool | None = None
    normalized_symptoms: list[str] = []
    debug_runtime: dict[str, Any] | None = None
    verification_result: dict[str, Any] | None = None
    verification_passed: bool | None = None
    verification_risk_level: str | None = None
    verification_issues: list[str] = []
    verification_summary: str | None = None
    status: str = "completed"
    confirm_message: str | None = None
    treatment_skipped_due_need_confirm: bool = False
    treatment_available: bool = False
    verification_available: bool = False
    manual_review_recommended: bool = False
    graph_treatment_generated: bool = False
    fallback_treatment_used: bool = False
    manual_review_required_before_execution: bool = False
    meta: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code != 404:
            return response

        if path.startswith("api/") or path.startswith("uploads/"):
            return response

        return await super().get_response("index.html", scope)

if LEGACY_WEB_DIR.exists():
    app.mount("/legacy", StaticFiles(directory=LEGACY_WEB_DIR), name="legacy")

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


NODE_MESSAGE_CN = {
    "ParseInput": "解析输入参数",
    "DiagnosisAgent": "进行图像/症状诊断",
    "ConfidenceGate": "评估置信度并决定回退",
    "PersonalizationAgent": "应用个性化约束",
    "KBRetrievalAgent": "检索知识库与方案",
    "PrescriptionAgent": "生成治疗与预防建议",
    "Persist": "落盘诊断与追踪事件",
    "Final": "返回最终结果",
    "AwaitUserConfirmation": "当前轮结束，等待用户补充",
}

USER_TEXT_CODE_MAP = {
    "FRUIT_SET": "坐果期",
    "SEEDLING": "苗期",
    "FLOWERING": "开花期",
    "HARVEST": "采收期",
}


def sanitize_user_text(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for code, label in USER_TEXT_CODE_MAP.items():
            text = text.replace(code, label)
        return text
    if isinstance(value, list):
        return [sanitize_user_text(item) for item in value]
    if isinstance(value, dict):
        return {k: sanitize_user_text(v) for k, v in value.items()}
    return value


GROWTH_STAGE_CANONICAL = {
    "苗期": "SEEDLING",
    "开花期": "FLOWERING",
    "坐果期": "FRUIT_SET",
    "结果期": "FRUIT_SET",
    "成熟期": "HARVEST",
}

RISK_CODE_ALIAS = {
    "开花期_fruiting_sensitive": "FLOWERING_FRUITING_SENSITIVE",
    "fruting_sensitive": "FLOWERING_FRUITING_SENSITIVE",
    "fruting": "FLOWERING_FRUITING_SENSITIVE",
}


def normalize_growth_stage_code(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    normalized = normalize_growth_stage(text)
    if normalized:
        return normalized
    return GROWTH_STAGE_CANONICAL.get(text, text)


def normalize_risk_code(code: Any) -> str:
    text = str(code or "").strip()
    if not text:
        return ""
    lowered = text.lower().replace("-", "_")
    if lowered in RISK_CODE_ALIAS:
        return RISK_CODE_ALIAS[lowered]
    if "开花期" in text and "FRUITING_SENSITIVE" in text:
        return "FLOWERING_FRUITING_SENSITIVE"
    return text.upper()


def normalize_risk_codes(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    tags = [normalize_risk_code(item) for item in (data.get("risk_tags") or []) if str(item).strip()]
    data["risk_tags"] = tags
    items = []
    for item in (data.get("risk_items") or []):
        if isinstance(item, dict):
            one = dict(item)
            one["code"] = normalize_risk_code(one.get("code") or one.get("label"))
            items.append(one)
    data["risk_items"] = items
    if tags:
        data["risk_summary"] = "、".join(tags)
    elif isinstance(data.get("risk_summary"), str):
        data["risk_summary"] = normalize_risk_code(data.get("risk_summary"))
    data["growth_stage"] = normalize_growth_stage_code(data.get("growth_stage"))
    return data


META_ONLY_CANONICAL_KEYS = {
    "growth_stage",
    "risk_tags",
    "risk_items",
    "risk_summary",
    "risk_updated_at",
}

LIST_FIELDS_ALWAYS = {
    "filtered_reasons",
    "filtered_components",
    "filtered_actions",
    "personalization_reasons",
    "follow_up_questions",
    "historical_follow_up_questions",
    "missing_profile_fields",
    "verification_issues",
    "text_top3",
    "fusion_top3",
    "normalized_symptoms",
    "model_fallback_reason",
    "events",
}


def _as_clean_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        seq = value
    elif isinstance(value, tuple):
        seq = list(value)
    else:
        seq = [value]
    return [item for item in seq if item is not None]


def _normalize_risk_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in _as_clean_list(items):
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif isinstance(item, dict):
            raw = dict(item)
        else:
            raw = {"code": str(item)}
        raw["code"] = normalize_risk_code(raw.get("code") or raw.get("label"))
        normalized.append(raw)
    return normalized


def _normalize_meta_payload(meta: Any) -> dict[str, Any]:
    payload = dict(meta) if isinstance(meta, dict) else {}

    payload["growth_stage"] = normalize_growth_stage_code(payload.get("growth_stage"))
    payload["risk_tags"] = [
        normalize_risk_code(item)
        for item in _as_clean_list(payload.get("risk_tags"))
        if str(item).strip()
    ]
    payload["risk_items"] = _normalize_risk_items(payload.get("risk_items"))

    if payload["risk_tags"]:
        payload["risk_summary"] = "、".join(payload["risk_tags"])
    elif isinstance(payload.get("risk_summary"), str):
        payload["risk_summary"] = normalize_risk_code(payload["risk_summary"])
    else:
        payload["risk_summary"] = None

    payload["equipment"] = [
        str(item).strip()
        for item in _as_clean_list(payload.get("equipment"))
        if str(item).strip()
    ]
    payload["banned_ingredients"] = [
        str(item).strip()
        for item in _as_clean_list(payload.get("banned_ingredients"))
        if str(item).strip()
    ]
    payload["model_fallback_reason"] = [
        str(item).strip()
        for item in _as_clean_list(payload.get("model_fallback_reason"))
        if str(item).strip()
    ]

    return payload


def _build_response_meta(
    *,
    flags: dict[str, Any],
    farmer_id: str | None,
    base_id: str | None,
    model_meta: dict[str, Any] | None,
    growth_stage: str | None,
) -> dict[str, Any]:
    meta = _build_personalization_meta(flags, farmer_id, base_id)
    meta["growth_stage"] = growth_stage or meta.get("growth_stage")

    model_meta = model_meta or {}
    meta["model_id"] = model_meta.get("model_id")
    meta["model_display_name"] = model_meta.get("model_display_name")
    meta["model_backend"] = model_meta.get("backend")
    meta["resolved_model_path"] = model_meta.get("resolved_model_path")
    meta["model_fallback_reason"] = model_meta.get("model_fallback_reason") or []

    return _normalize_meta_payload(meta)


def _build_personalization_runtime_snapshot(
    *,
    personalization_applied: bool,
    selected_branch: str | None,
    llm_failed: bool,
    filtered: bool,
    filtered_reasons: list[str],
    filtered_components: list[str],
    filtered_actions: list[str],
    personalization_reasons: list[str],
    follow_up_questions: list[str],
    missing_profile_fields: list[str],
    personalization_context: str | None,
) -> dict[str, Any]:
    return {
        "personalization_applied": personalization_applied,
        "selected_branch": selected_branch,
        "llm_failed": llm_failed,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "personalization_reasons": personalization_reasons,
        "follow_up_questions": follow_up_questions,
        "missing_profile_fields": missing_profile_fields,
        "personalization_context": personalization_context,
    }


def merge_follow_up_questions(
    historical: list[str],
    current: list[str],
    *,
    active: bool,
) -> tuple[list[str], list[str]]:
    merged_historical: list[str] = []
    for item in [*historical, *current]:
        text = str(item).strip()
        if text and text not in merged_historical:
            merged_historical.append(text)
    visible_current = [str(item).strip() for item in current if str(item).strip()] if active else []
    return visible_current, merged_historical


def serialize_final_response(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    meta = dict(data.get("meta") or {})

    # canonical 统一进 meta，root 不再重复
    for key in META_ONLY_CANONICAL_KEYS:
        if key in data and key not in meta:
            meta[key] = data[key]
        data.pop(key, None)

    if meta:
        data["meta"] = _normalize_meta_payload(meta)

    for key in LIST_FIELDS_ALWAYS:
        data[key] = _as_clean_list(data.get(key))

    if "verification_summary" in data and data["verification_summary"] is not None:
        data["verification_summary"] = sanitize_user_text(data["verification_summary"])

    treatment = data.get("treatment")
    if isinstance(treatment, dict):
        treatment = dict(treatment)
        treatment["plan"] = sanitize_user_text(treatment.get("plan"))
        treatment["prevention"] = sanitize_user_text(treatment.get("prevention"))
        data["treatment"] = treatment

    if "confirm_message" in data and data["confirm_message"] is not None:
        data["confirm_message"] = sanitize_user_text(data["confirm_message"])

    if "meta" in data:
        data["meta"] = sanitize_user_text(data["meta"])

    return sanitize_user_text(data)


def emit_node_event(
    trace_id: str,
    *,
    node: str,
    status: str,
    message: str | None = None,
    payload: dict | None = None,
) -> dict:
    return emit_trace_event(
        trace_id,
        {
            "node": node,
            "status": status,
            "message": message or NODE_MESSAGE_CN.get(node, node),
            "payload": payload or {},
        },
    )


TERMINAL_CASE_STATUSES = {"completed", "manual_review_recommended", "failed", "cancelled"}


def has_terminal_final_event(trace_id: str) -> bool:
    for event in list_trace_events(trace_id):
        if event.get("node") != "Final":
            continue
        if str(event.get("status") or "").lower() in {"end", "error"}:
            return True
    return False


def emit_final_event_once(
    trace_id: str,
    *,
    status: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """仅在终态且未存在 Final.end/error 时写入 Final 事件。"""
    if status not in TERMINAL_CASE_STATUSES:
        return False
    if has_terminal_final_event(trace_id):
        return False
    emit_node_event(trace_id, node="Final", status="end", message=message, payload=payload)
    return True


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


def serve_frontend_index() -> Response:
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return PlainTextResponse(
        "前端构建产物不存在，请先执行：cd app && npm run build",
        status_code=503,
    )


@app.get("/")
def index() -> Response:
    return serve_frontend_index()


def serve_frontend_path(path: str) -> Response:
    safe_path = Path(path)
    if safe_path.is_absolute() or ".." in safe_path.parts:
        return serve_frontend_index()

    target = (FRONTEND_DIR / safe_path).resolve()
    frontend_root = FRONTEND_DIR.resolve()
    if not str(target).startswith(str(frontend_root)):
        return serve_frontend_index()

    if target.exists() and target.is_file():
        return FileResponse(target)

    return serve_frontend_index()


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


def _resolve_profile_and_base(
    farmer_id: str | None,
    base_id: str | None,
) -> tuple[FarmerProfile | None, BaseProfile | None, str | None]:
    if not farmer_id:
        return None, None, base_id
    profile = load_profile(farmer_id)
    if not profile:
        return None, None, base_id

    resolved_base_id = base_id or profile.active_base_id
    base_profile = None
    if profile.bases:
        if resolved_base_id and resolved_base_id in profile.bases:
            base_profile = profile.bases[resolved_base_id]
        else:
            resolved_base_id = next(iter(profile.bases.keys()))
            base_profile = profile.bases[resolved_base_id]
    return profile, base_profile, resolved_base_id


def _build_personalization_meta(flags: dict, farmer_id: str | None, base_id: str | None) -> dict:
    risk_tags = [
        normalize_risk_code(item)
        for item in (flags.get("risk_tags") or [])
        if str(item).strip()
    ]
    risk_items = _normalize_risk_items(flags.get("risk_items"))

    return {
        "farmer_id": farmer_id,
        "base_id": base_id,
        "prefer_organic": bool(flags.get("prefer_organic")),
        "banned_ingredients": flags.get("banned_ingredients") or [],
        "harvest_window_days": flags.get("harvest_window_days"),
        "facility": flags.get("facility"),
        "environment": flags.get("environment"),
        "growth_stage": normalize_growth_stage_code(flags.get("growth_stage")),
        "farm_scale": flags.get("farm_scale"),
        "pesticide_access_level": flags.get("pesticide_access_level"),
        "equipment": flags.get("equipment") or [],
        "cultivation_mode": flags.get("cultivation_mode"),
        "experience_level": flags.get("experience_level"),
        "risk_preference": flags.get("risk_preference"),
        "risk_tags": risk_tags,
        "risk_items": risk_items,
        "risk_updated_at": flags.get("risk_updated_at"),
        "risk_summary": "、".join(risk_tags) if risk_tags else None,
    }


def resume_from_confirm_input(
    state: dict[str, Any],
    *,
    crop_type: str,
    growth_stage: str | None,
    model_id: str | None,
    image_path: str,
    merged_symptoms: list[str],
) -> dict[str, Any]:
    """将确认输入补丁写入状态，并回到 supervisor 可调度的诊断入口。"""
    state["image_path"] = image_path
    state["symptoms"] = merged_symptoms
    state["crop_type"] = crop_type
    state["crop_growth_stage"] = normalize_growth_stage_code(growth_stage)
    state["diagnosis_model_id"] = model_id
    state["current_step"] = "confirm_input"
    return state


def _normalize_filter_state(flags: dict) -> tuple[bool, list[str], list[str], list[str]]:
    """在 API 层做 filtered/filtered_reasons 的最终一致性兜底。

    语义约定：
    - filtered 表示最终文本是否发生了个性化后处理变更。
    - filtered_reasons 表示发生变更的原因。
    - filtered_components 表示被删除/替换/弱化命中的成分或关键词（可为空）。
    - filtered_actions 表示变更动作类型。
    """
    normalized = profile_rules.normalize_filter_outputs({
        "filtered": flags.get("filtered", False),
        "filtered_reasons": flags.get("filtered_reasons") or [],
        "filtered_components": flags.get("filtered_components") or [],
        "personalization_applied": flags.get("personalization_applied", False),
        "filtered_actions": flags.get("filtered_actions") or [],
    })
    flags.update(normalized)
    return (
        bool(normalized["filtered"]),
        list(normalized["filtered_reasons"]),
        list(normalized["filtered_components"]),
        list(normalized.get("filtered_actions") or []),
    )




def _build_degraded_treatment(
    disease_name: str,
    flags: dict,
) -> tuple[TreatmentPlan | None, dict]:
    """图流程异常时的兜底治疗方案：KB 优先 + 个性化约束过滤。"""
    try:
        kb_result = kb.get_treatment_plan(disease_name or "") or {}
        kb_treatment = str(kb_result.get("treatment") or "").strip()
        kb_prevention = str(kb_result.get("prevention") or "").strip()
    except Exception:
        kb_treatment = ""
        kb_prevention = ""

    if not kb_treatment:
        kb_treatment = f"针对{disease_name or '疑似病害'}：先隔离重病叶，降低田间湿度并连续观察48小时。"
    if not kb_prevention:
        kb_prevention = "加强通风、清园与轮作，避免长期高湿环境。"

    personalized_plan, personalized_prevention, personalization_outputs = profile_rules.apply_personalization_to_treatment(
        kb_treatment,
        kb_prevention,
        flags,
    )
    plan_text = (personalized_plan or kb_treatment).strip()
    prevention_text = (personalized_prevention or kb_prevention).strip()
    if not plan_text and not prevention_text:
        return None, personalization_outputs
    return TreatmentPlan(plan=plan_text, prevention=prevention_text), personalization_outputs

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
        parts.append(f"生长阶段：{growth_stage_label(growth_stage)}")
    if symptoms_list:
        parts.append(f"症状：{', '.join(symptoms_list)}")
    parts.append(f"图片路径：{image_path}")
    return "，".join(parts)


def _collect_runtime_debug() -> dict[str, Any]:
    git_commit = None
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parent), text=True).strip()
    except Exception:
        git_commit = None
    return {
        "app_file": __file__,
        "agents_file": getattr(agents_module, "__file__", None),
        "diagnosis_model_file": getattr(diagnosis_model_module, "__file__", None),
        "kb_manager_file": getattr(kb_manager_module, "__file__", None),
        "git_commit": git_commit,
        "fuse_multimodal_version": getattr(diagnosis_model_module, "FUSE_MULTIMODAL_VERSION", None),
        "predict_text_proba_version": getattr(diagnosis_model_module, "PREDICT_TEXT_PROBA_VERSION", None),
    }


@app.post("/api/diagnose-image", response_model=DiagnoseResponse, response_model_exclude_none=True)
async def diagnose_image(
    file: UploadFile = File(...),
    crop_type: str = Form("番茄"),
    symptoms: str | None = Form(None),
    growth_stage: str | None = Form(None),
    model_id: str | None = Form(None),
    farmer_id: str | None = Form(None),
    base_id: str | None = Form(None),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    debug_runtime: bool | None = Form(None),
) -> DiagnoseResponse:
    request_started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    emit_node_event(trace_id, node="ParseInput", status="start", message="开始解析上传请求")
    debug_mode = bool(debug_runtime) or str(os.getenv("DIAG_DEBUG_RUNTIME", "0")).lower() in {"1", "true", "yes"}
    runtime_debug = _collect_runtime_debug() if debug_mode else None
    if debug_mode:
        print(f"[RuntimeDebug] {json.dumps(runtime_debug, ensure_ascii=False)}")
    if not file.filename:
        emit_node_event(trace_id, node="ParseInput", status="error", message="文件名为空")
        emit_node_event(trace_id, node="Final", status="error", message="请求解析失败")
        raise HTTPException(status_code=400, detail="文件名为空")

    suffix = Path(file.filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    if suffix not in IMAGE_EXTS and not content_type.startswith("image/"):
        emit_node_event(trace_id, node="ParseInput", status="error", message="上传文件类型不支持")
        emit_node_event(trace_id, node="Final", status="error", message="请求解析失败")
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
        emit_node_event(trace_id, node="ParseInput", status="end", message="输入解析完成", payload={"image_path": str(saved_path)})
    except HTTPException:
        emit_node_event(trace_id, node="ParseInput", status="error", message="输入解析失败")
        emit_node_event(trace_id, node="Final", status="error", message="请求解析失败")
        raise
    except Exception as exc:
        emit_node_event(trace_id, node="ParseInput", status="error", message=f"读取或保存失败: {exc}")
        emit_node_event(trace_id, node="Final", status="error", message="请求解析失败")
        raise HTTPException(status_code=400, detail=f"读取或保存图片失败: {exc}") from exc

    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    emit_node_event(trace_id, node="DiagnosisAgent", status="start", message="正在进行图像诊断")
    resolved_model, model_fallback_reason = resolve_model(model_id, allow_torch=allow_torch)
    engine = get_diagnosis_engine(
        model_path=resolved_model.model_path,
        backend=resolved_model.backend,
        allow_torch=allow_torch,
    )
    disease, conf, probs = engine.diagnose_from_image(str(saved_path))
    disease = disease or "未知病害"
    conf = float(conf or 0.0)

    if disease == "模型未部署":
        emit_node_event(trace_id, node="DiagnosisAgent", status="error", message="模型未部署")
        emit_node_event(trace_id, node="Final", status="error", message="诊断失败")
        raise HTTPException(status_code=500, detail="模型未部署，请先配置并加载模型")
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
    emit_node_event(trace_id, node="DiagnosisAgent", status="end", message="图像诊断完成", payload={"disease": disease, "confidence": conf})
    emit_node_event(trace_id, node="ConfidenceGate", status="start", message="评估置信度")
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
            emit_node_event(trace_id, node="ConfidenceGate", status="end", message="触发症状回退", payload={"reasons": fallback_reasons})
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
            emit_node_event(trace_id, node="ConfidenceGate", status="error", message=f"症状回退失败: {exc}")

    if not (fallback_condition and symptoms_list):
        emit_node_event(trace_id, node="ConfidenceGate", status="end", message="无需回退", payload={"reasons": fallback_reasons})

    final_disease = disease
    if fallback_used and rule_result and rule_result.rule_disease:
        final_disease = rule_result.rule_disease

    treatment: TreatmentPlan | None = None

    profile, base_profile, resolved_base_id = _resolve_profile_and_base(farmer_id, base_id)
    personalization_context = build_personalization_context(profile, base_profile)
    personalization_flags = build_personalization_flags(profile, base_profile)
    personalization_meta = _build_personalization_meta(personalization_flags, farmer_id, resolved_base_id)

    personalization_applied = False
    filtered = False
    filtered_reasons: list[str] = []
    filtered_components: list[str] = []
    personalization_reasons: list[str] = []

    image_result_dict = {
        "disease": disease,
        "confidence": conf,
        "confidence_pct": round(conf * 100, 2),
        "top3": top3,
    }
    rule_result_dict = rule_result.model_dump() if rule_result else None
    image_url = f"/uploads/{unique_name}"

    need_confirm = None
    trace_fallback_reason: list[str] | None = None
    final_confidence = None
    final_source = None
    final_state = None
    workflow_degraded = False
    degraded_reason: str | None = None
    text_top3: list[tuple[str, float]] = []
    fusion_top3: list[tuple[str, float]] = []
    diagnosis_evidence: dict[str, Any] | None = None
    modality_conflict_flag: bool | None = None
    normalized_symptoms: list[str] = []
    try:
        query_text = build_trace_query(
            crop_type=crop_type,
            symptoms_list=symptoms_list,
            growth_stage=growth_stage,
            image_path=str(saved_path),
        )
        initial_state = create_initial_state(query_text, farmer_id=farmer_id, base_id=base_id)
        initial_state["diagnosis_model_id"] = resolved_model.model_id
        if personalization_context:
            initial_state["personalization_context"] = personalization_context
        if personalization_flags:
            initial_state["personalization_flags"] = dict(personalization_flags)
        if debug_mode:
            flags = dict(initial_state.get("personalization_flags") or {})
            flags["debug_runtime"] = True
            initial_state["personalization_flags"] = flags
            initial_state["debug_runtime"] = runtime_debug
        graph = build_graph()
        final_state = graph.invoke(initial_state, config={"recursion_limit": 80})
        if not isinstance(final_state, dict):
            raise RuntimeError("GRAPH_EMPTY_FINAL_STATE")
        trace_id = final_state.get("trace_id", trace_id)
    except Exception as exc:
        print(f"Warning: failed to build trace events: {exc}")
        lowered = str(exc).lower()
        degraded_reason = "GRAPH_RECURSION_LIMIT" if "recursion" in lowered else str(exc)
        workflow_degraded = True
        fallback_treatment, personalization_outputs = _build_degraded_treatment(final_disease, dict(personalization_flags))
        if fallback_treatment:
            treatment = fallback_treatment
        personalization_flags.update(personalization_outputs)

    flags = dict(personalization_flags)
    graph_treatment_generated = False
    if final_state:
        final_disease = final_state.get("final_disease") or final_disease
        flags = final_state.get("personalization_flags") or flags
        need_confirm = flags.get("need_confirm")
        trace_fallback_reason = flags.get("fallback_reason")
        final_confidence = final_state.get("final_confidence")
        final_source = final_state.get("final_source")
        treatment_plan = (final_state.get("treatment_plan") or "").strip()
        prevention_advice = (final_state.get("prevention_advice") or "").strip()
        if treatment_plan or prevention_advice:
            treatment = TreatmentPlan(plan=treatment_plan, prevention=prevention_advice)
            graph_treatment_generated = True
        personalization_reasons = dedupe_reasons(final_state.get("personalization_reasons") or [])

    verification_result = (final_state or {}).get("verification_result")
    verification_passed = (final_state or {}).get("verification_passed")
    verification_risk_level = (final_state or {}).get("verification_risk_level")
    verification_issues = list((final_state or {}).get("verification_issues") or [])
    verification_summary = (final_state or {}).get("verification_summary")

    need_confirm_waiting = bool(need_confirm is True and not graph_treatment_generated)
    fallback_treatment_used = False
    if treatment is None and not need_confirm_waiting:
        fallback_treatment, personalization_outputs = _build_degraded_treatment(final_disease, dict(flags))
        if fallback_treatment:
            treatment = fallback_treatment
            fallback_treatment_used = True
        flags.update(personalization_outputs)
        if not workflow_degraded:
            workflow_degraded = True
            degraded_reason = degraded_reason or "EMPTY_TREATMENT_FROM_GRAPH"
    elif need_confirm_waiting:
        treatment = None
        verification_result = None
        verification_passed = None
        verification_risk_level = None
        verification_issues = []
        verification_summary = None
        workflow_degraded = False
        degraded_reason = None

    follow_up_questions = normalize_follow_up_questions(flags.get("follow_up_questions") or [])
    flags["follow_up_questions"] = follow_up_questions
    missing_profile_fields = sorted({str(item).strip() for item in (flags.get("missing_profile_fields") or []) if str(item).strip()})
    personalization_state = final_state if isinstance(final_state, dict) else {
        "farmer_id": farmer_id,
        "personalization_context": personalization_context,
        "personalization_reasons": personalization_reasons,
        "follow_up_questions": follow_up_questions,
        "missing_profile_fields": missing_profile_fields,
    }
    personalization_applied = compute_personalization_applied(personalization_state, flags)
    flags["personalization_applied"] = personalization_applied
    filtered, filtered_reasons, filtered_components, filtered_actions = _normalize_filter_state(flags)
    if not personalization_reasons:
        personalization_reasons = dedupe_reasons(flags.get("personalization_reasons") or [])
    else:
        personalization_reasons = dedupe_reasons(personalization_reasons)
    flags["personalization_reasons"] = dedupe_reasons(flags.get("personalization_reasons") or personalization_reasons)

    trace_personalization_outputs = _build_personalization_runtime_snapshot(
        personalization_applied=personalization_applied,
        selected_branch=flags.get("selected_branch"),
        llm_failed=bool(flags.get("llm_failed")),
        filtered=filtered,
        filtered_reasons=filtered_reasons,
        filtered_components=filtered_components,
        filtered_actions=filtered_actions,
        personalization_reasons=personalization_reasons,
        follow_up_questions=follow_up_questions,
        missing_profile_fields=missing_profile_fields,
        personalization_context=personalization_context,
    )
    emit_node_event(
        trace_id,
        node="PersonalizationAgent",
        status="end",
        message="个性化结果来自LangGraph输出" if farmer_id else "未提供个性化档案，跳过",
        payload={
            "outputs": trace_personalization_outputs,
            "canonical_meta": personalization_meta,
            "runtime_snapshot": trace_personalization_outputs,
        },
    )

    treatment_or_none = treatment.model_dump() if treatment else None

    model_meta = (final_state or {}).get("diagnosis_model_meta") or {
        "model_id": resolved_model.model_id,
        "model_display_name": resolved_model.display_name,
        "backend": resolved_model.backend,
        "resolved_model_path": resolved_model.model_path,
        "model_fallback_reason": model_fallback_reason,
    }

    response_status = "waiting_for_confirmation" if need_confirm_waiting else "completed"
    verification_available = verification_result is not None
    treatment_available = treatment is not None
    response_fallback_reason = (trace_fallback_reason or fallback_reasons or None) if fallback_used else None
    canonical_risk_tags = [normalize_risk_code(item) for item in (flags.get("risk_tags") or []) if str(item).strip()]
    canonical_risk_items = []
    for item in (flags.get("risk_items") or []):
        if hasattr(item, "model_dump"):
            raw = item.model_dump()
        elif isinstance(item, dict):
            raw = dict(item)
        else:
            raw = {"code": str(item)}
        raw["code"] = normalize_risk_code(raw.get("code") or raw.get("label"))
        canonical_risk_items.append(raw)
    canonical_growth_stage = normalize_growth_stage_code((final_state or {}).get("crop_growth_stage") or growth_stage)
    if treatment is not None:
        treatment = TreatmentPlan(
            plan=str(sanitize_user_text(treatment.plan)),
            prevention=str(sanitize_user_text(treatment.prevention)),
        )
    verification_summary = sanitize_user_text(verification_summary)

    response_meta = _build_response_meta(
        flags=flags,
        farmer_id=farmer_id,
        base_id=resolved_base_id,
        model_meta=model_meta,
        growth_stage=canonical_growth_stage,
    )

    event = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "trace_id": trace_id,
        "crop_type": crop_type,
        "symptoms": symptoms_list,
        "image_id": unique_name,
        "image_url": image_url,
        "image_result": image_result_dict,
        "fallback_used": fallback_used,
        "fallback_reason": response_fallback_reason,
        "rule_result": rule_result_dict,
        "final_disease": final_state.get("final_disease") if final_state else final_disease,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "confirm_round": False,
        "source_stage": "initial",
        "selected_branch": flags.get("selected_branch"),
        "personalization_applied": personalization_applied,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "llm_failed": bool(flags.get("llm_failed")),
        "elapsed_ms": round((time.perf_counter() - request_started) * 1000, 2),
        "image_confidence": final_state.get("image_confidence") if final_state else None,
        "treatment": treatment_or_none,
        "meta": response_meta,
        "verification_result": verification_result,
        "verification_passed": verification_passed,
        "verification_risk_level": verification_risk_level,
        "verification_issues": verification_issues,
        "verification_summary": verification_summary,
        "status": response_status,
        "treatment_skipped_due_need_confirm": need_confirm_waiting,
        "treatment_available": treatment_available,
        "verification_available": verification_available,
        "manual_review_recommended": False,
        "manual_review_required_before_execution": False,
        "graph_treatment_generated": graph_treatment_generated,
        "fallback_treatment_used": fallback_treatment_used,
    }
    event = serialize_final_response(event)
    emit_node_event(trace_id, node="Persist", status="start", message="写入事件日志")
    try:
        append_event(event)
        emit_node_event(trace_id, node="Persist", status="end", message="事件落盘完成")
    except Exception as exc:
        print(f"Warning: failed to append event: {exc}")
        emit_node_event(trace_id, node="Persist", status="error", message=f"事件落盘失败: {exc}")

    if response_status == "waiting_for_confirmation":
        emit_node_event(
            trace_id,
            node="AwaitUserConfirmation",
            status="end",
            message="当前轮返回追问，等待用户补充后进入二次诊断",
            payload={"final_disease": final_disease, "status": response_status, "reason": "need_confirm_wait_user"},
        )
    else:
        emit_final_event_once(
            trace_id,
            status=response_status,
            message="诊断流程完成",
            payload={"final_disease": final_disease, "status": response_status},
        )

    response_payload = {
        "image_id": unique_name,
        "image_url": image_url,
        "image_result": image_result_dict,
        "fallback_used": fallback_used,
        "fallback_reason": response_fallback_reason,
        "rule_result": rule_result_dict,
        "final_disease": final_disease,
        "treatment": treatment_or_none,
        "personalization_applied": personalization_applied,
        "farmer_id": farmer_id,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "personalization_reasons": personalization_reasons,
        "follow_up_questions": follow_up_questions,
        "historical_follow_up_questions": [],
        "missing_profile_fields": missing_profile_fields,
        "profile_farm_scale": flags.get("farm_scale"),
        "profile_pesticide_access_level": flags.get("pesticide_access_level"),
        "profile_equipment": [str(item) for item in (flags.get("equipment") or [])],
        "profile_cultivation_mode": flags.get("cultivation_mode"),
        "selected_branch": flags.get("selected_branch") if treatment_available else None,
        "llm_failed": bool(flags.get("llm_failed")),
        "trace_id": trace_id,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "model_id": model_meta.get("model_id"),
        "model_display_name": model_meta.get("model_display_name"),
        "model_backend": model_meta.get("backend"),
        "resolved_model_path": model_meta.get("resolved_model_path"),
        "model_fallback_reason": model_meta.get("model_fallback_reason"),
        "text_top3": list((final_state or {}).get("text_top3") or []),
        "fusion_top3": list((final_state or {}).get("fusion_top3") or []),
        "diagnosis_evidence": (final_state or {}).get("diagnosis_evidence"),
        "modality_conflict_flag": (final_state or {}).get("modality_conflict_flag"),
        "normalized_symptoms": list(
            (final_state or {}).get("normalized_symptoms")
            or ((final_state or {}).get("structured_symptoms") or {}).get("normalized_symptoms")
            or []
        ),
        "workflow_degraded": workflow_degraded,
        "degraded_reason": degraded_reason,
        "verification_result": verification_result,
        "verification_passed": verification_passed,
        "verification_risk_level": verification_risk_level,
        "verification_issues": verification_issues,
        "verification_summary": verification_summary,
        "status": response_status,
        "confirm_message": None,
        "treatment_skipped_due_need_confirm": need_confirm_waiting,
        "treatment_available": treatment_available,
        "verification_available": verification_available,
        "manual_review_recommended": False,
        "manual_review_required_before_execution": False,
        "graph_treatment_generated": graph_treatment_generated,
        "fallback_treatment_used": fallback_treatment_used,
        "meta": response_meta,
        "events": list_trace_events(trace_id),
        "debug_runtime": {
            **(runtime_debug or {}),
            "diagnosis_debug": (final_state or {}).get("debug_diagnosis"),
        } if debug_mode else None,
    }

    return DiagnoseResponse(**serialize_final_response(response_payload))


@app.post("/api/diagnose-confirm")
def diagnose_confirm(payload: dict = Body(...)) -> dict:
    request_started = time.perf_counter()
    trace_id = payload.get("trace_id")
    previous_trace_id = payload.get("previous_trace_id")
    image_id = payload.get("image_id")
    crop_type = payload.get("crop_type") or "番茄"
    symptoms = payload.get("symptoms") or []
    growth_stage = payload.get("growth_stage")
    model_id = payload.get("model_id")
    choice = str(payload.get("choice") or "").strip()
    farmer_id = payload.get("farmer_id")
    base_id = payload.get("base_id")

    if not image_id:
        raise HTTPException(status_code=400, detail="image_id 不能为空")

    # 保持二次诊断沿用首轮 trace，便于流程面板展示完整链路
    if not trace_id and previous_trace_id:
        trace_id = previous_trace_id
    if not trace_id:
        trace_id = uuid.uuid4().hex

    if not isinstance(symptoms, list):
        raise HTTPException(status_code=400, detail="symptoms 必须为列表")

    # ConfirmFlow 是低置信度回退分支（复用同一 trace），不是独立于主图的平行业务流程。
    # 因此确认输入症状必须与上一轮症状做增量合并，避免覆盖。
    history_events = list_trace_events(trace_id)
    historical_symptoms: list[str] = []
    for event_like in reversed(history_events):
        if not isinstance(event_like, dict):
            continue
        for section in ("outputs", "inputs", "payload"):
            container = event_like.get(section)
            if isinstance(container, dict) and isinstance(container.get("symptoms"), list):
                historical_symptoms = [str(item).strip() for item in container.get("symptoms", []) if str(item).strip()]
                break
        if historical_symptoms:
            break
    symptom_alias_map = {
        "病斑原形": "病斑圆形",
        "水渍壮": "水渍状",
        "卷叶": "叶片卷曲",
    }
    incoming_symptoms = [str(item).strip() for item in symptoms if str(item).strip()]
    incoming_symptoms = [symptom_alias_map.get(item, item) for item in incoming_symptoms]
    historical_symptoms = [symptom_alias_map.get(item, item) for item in historical_symptoms]
    merged_symptoms: list[str] = []
    for symptom in [*historical_symptoms, *incoming_symptoms]:
        if symptom and symptom not in merged_symptoms:
            merged_symptoms.append(symptom)

    emit_node_event(trace_id, node="ConfirmFlow", status="start", message="开始二次诊断确认")

    image_path = (UPLOAD_DIR / image_id).resolve()
    if not image_path.exists():
        emit_node_event(trace_id, node="ConfirmFlow", status="error", message="二次诊断图片不存在")
        raise HTTPException(status_code=404, detail="图片不存在")

    state = create_initial_state(f"confirm:{image_id}", farmer_id=farmer_id, base_id=base_id)
    profile, base_profile, resolved_base_id = _resolve_profile_and_base(farmer_id, base_id)
    if resolved_base_id:
        state["base_id"] = resolved_base_id
    personalization_context = build_personalization_context(profile, base_profile)
    personalization_flags = build_personalization_flags(profile, base_profile)
    if personalization_context:
        state["personalization_context"] = personalization_context
    if personalization_flags:
        state["personalization_flags"] = personalization_flags
    state["trace_id"] = trace_id
    previous_step_count = 0
    previous_follow_ups: list[str] = []
    confirm_round_index = 1
    for event_like in history_events:
        if not isinstance(event_like, dict):
            continue
        if event_like.get("agent") == "supervisor":
            inputs = event_like.get("inputs")
            if isinstance(inputs, dict):
                previous_step_count = max(previous_step_count, int(inputs.get("step_count") or 0))
        for section in ("outputs", "inputs", "payload"):
            container = event_like.get(section)
            if isinstance(container, dict) and isinstance(container.get("follow_up_questions"), list):
                previous_follow_ups.extend([str(x).strip() for x in container.get("follow_up_questions") if str(x).strip()])
        if event_like.get("agent") == "confirm_input":
            confirm_round_index += 1

    state["step_count"] = previous_step_count
    state = resume_from_confirm_input(
        state,
        crop_type=crop_type,
        growth_stage=growth_stage,
        model_id=model_id,
        image_path=str(image_path),
        merged_symptoms=merged_symptoms,
    )

    append_trace(
        state,
        agent="confirm_input",
        inputs={
            "symptoms": state["symptoms"],
            "historical_symptoms": historical_symptoms,
            "incoming_symptoms": incoming_symptoms,
            "crop_type": crop_type,
            "growth_stage": growth_stage,
            "image_id": image_id,
            "previous_trace_id": previous_trace_id,
            "model_id": model_id,
            "choice": choice,
            "farmer_id": farmer_id,
            "base_id": base_id,
            "confirm_round_index": confirm_round_index,
        },
        outputs={},
    )

    if choice and choice != "other":
        state["final_disease"] = choice
        state["disease_type"] = choice
        flags = state.get("personalization_flags") or {}
        flags["need_confirm"] = False
        state["personalization_flags"] = flags
        append_trace(
            state,
            agent="confirm_choice",
            inputs={"choice": choice},
            outputs={"final_disease": choice, "need_confirm": False},
        )

    # 低置信度回退分支：由 supervisor 做统一路由决策，避免形成平行独立流程。
    for _ in range(10):
        state = supervisor_agent(state)
        next_action = str(state.get("next_action") or "")
        if next_action == "diagnosis":
            state = diagnosis_agent(state)
        elif next_action == "kb_retrieval":
            state = kb_retrieval_agent(state)
        elif next_action == "treatment":
            state = treatment_agent(state)
        elif next_action == "verification":
            state = verification_agent(state)
        elif next_action == "end":
            break
        else:
            break

    final_confidence = state.get("final_confidence")
    final_source = state.get("final_source")
    image_confidence = state.get("image_confidence")
    text_confidence = state.get("text_confidence")
    text_top3 = list(state.get("text_top3") or [])
    fusion_top3 = list(state.get("fusion_top3") or [])
    modality_conflict_flag = state.get("modality_conflict_flag")
    diagnosis_evidence = state.get("diagnosis_evidence")

    image_diagnosis = state.get("image_diagnosis") or {}
    image_top1 = image_diagnosis.get("top1") or {}
    top3 = image_diagnosis.get("top3") or []
    image_result = {
        "disease": image_top1.get("disease"),
        "confidence": float(image_top1.get("confidence") or 0.0),
        "confidence_pct": round(float(image_top1.get("confidence") or 0.0) * 100, 2),
        "top3": [
            {"disease": name, "prob": float(prob), "prob_pct": round(float(prob) * 100, 2)}
            for name, prob in top3
        ],
    }
    flags = state.get("personalization_flags") or {}
    need_confirm = bool(flags.get("need_confirm"))
    if choice and choice != "other":
        need_confirm = False
    manual_review_recommended = need_confirm
    if manual_review_recommended:
        need_confirm = False
    manual_review_required_before_execution = manual_review_recommended
    if manual_review_recommended:
        state["treatment_plan"] = None
        state["prevention_advice"] = None
        state["verification_result"] = None
        state["verification_passed"] = None
        state["verification_risk_level"] = None
        state["verification_issues"] = []
        state["verification_summary"] = None

    state["current_step"] = "uncertainty_router"
    append_trace(
        state,
        agent="uncertainty_router",
        inputs={
            "need_confirm_from_diagnosis": bool(flags.get("need_confirm")),
            "verification_passed": state.get("verification_passed"),
        },
        outputs={
            "need_confirm": need_confirm,
            "manual_review_recommended": manual_review_recommended,
            "manual_review_required_before_execution": manual_review_required_before_execution,
            "status": "manual_review_recommended" if manual_review_recommended else "completed",
        },
        decision={
            "reason": "二诊后仍存在不确定性，转换为人工复核建议" if manual_review_recommended else "二诊确定，可正常收尾",
        },
    )

    state["current_step"] = "confirm_finalize"
    append_trace(
        state,
        agent="confirm_finalize",
        inputs={"choice": choice or "other"},
        outputs={
            "final_disease": state.get("final_disease"),
            "need_confirm": need_confirm,
            "has_treatment": bool(state.get("treatment_plan")),
        },
    )

    personalization_applied = compute_personalization_applied(state, flags)
    flags["personalization_applied"] = personalization_applied
    filtered, filtered_reasons, filtered_components, filtered_actions = _normalize_filter_state(flags)
    follow_up_questions_raw = normalize_follow_up_questions(flags.get("follow_up_questions") or [])
    follow_up_questions, historical_follow_up_questions = merge_follow_up_questions(
        previous_follow_ups,
        follow_up_questions_raw,
        active=bool(need_confirm),
    )
    flags["follow_up_questions"] = follow_up_questions
    missing_profile_fields = sorted({str(item).strip() for item in (flags.get("missing_profile_fields") or []) if str(item).strip()})
    confirm_message = None
    if manual_review_recommended:
        confirm_message = "二次诊断后仍存在不确定性，建议人工复核后再执行方案"
    elif need_confirm:
        confirm_message = "置信度较低，建议补充症状或重新拍摄"

    emit_node_event(
        trace_id,
        node="ConfirmFlow",
        status="end",
        message="二次诊断确认完成",
        payload={
            "need_confirm": need_confirm,
            "manual_review_recommended": manual_review_recommended,
            "final_disease": state.get("final_disease"),
        },
    )
    confirm_status = "manual_review_recommended" if manual_review_recommended else "completed"

    model_meta = state.get("diagnosis_model_meta") or {}
    response_meta = _build_response_meta(
        flags=flags,
        farmer_id=farmer_id,
        base_id=state.get("base_id"),
        model_meta=model_meta,
        growth_stage=normalize_growth_stage_code(state.get("crop_growth_stage") or growth_stage),
    )
    event = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "trace_id": trace_id,
        "crop_type": crop_type,
        "symptoms": state.get("symptoms") or [],
        "image_id": image_id,
        "image_url": f"/uploads/{image_id}",
        "image_result": image_result,
        "fallback_used": False,
        "fallback_reason": None,
        "rule_result": None,
        "final_disease": state.get("final_disease"),
        "need_confirm": need_confirm,
        "final_confidence": final_confidence if final_confidence is not None else image_result.get("confidence"),
        "final_source": final_source or "confirm",
        "confirm_round": True,
        "source_stage": "confirm",
        "selected_branch": flags.get("selected_branch"),
        "personalization_applied": personalization_applied,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "llm_failed": bool(flags.get("llm_failed")),
        "elapsed_ms": round((time.perf_counter() - request_started) * 1000, 2),
        "treatment": None if manual_review_recommended else {
            "plan": state.get("treatment_plan"),
            "prevention": state.get("prevention_advice"),
        },
        "meta": response_meta,
        "verification_result": None if manual_review_recommended else state.get("verification_result"),
        "verification_passed": None if manual_review_recommended else state.get("verification_passed"),
        "verification_risk_level": None if manual_review_recommended else state.get("verification_risk_level"),
        "verification_issues": [] if manual_review_recommended else list(state.get("verification_issues") or []),
        "verification_summary": None if manual_review_recommended else state.get("verification_summary"),
        "image_confidence": image_confidence,
        "text_confidence": text_confidence,
        "text_top3": text_top3,
        "fusion_top3": fusion_top3,
        "modality_conflict_flag": modality_conflict_flag,
        "diagnosis_evidence": diagnosis_evidence,
        "manual_review_recommended": manual_review_recommended,
        "manual_review_required_before_execution": manual_review_required_before_execution,
        "status": confirm_status,
        "treatment_available": bool(state.get("treatment_plan")) and not manual_review_recommended,
        "verification_available": (state.get("verification_result") is not None) and not manual_review_recommended,
        "graph_treatment_generated": bool(state.get("treatment_plan")),
        "fallback_treatment_used": False,
        "historical_follow_up_questions": historical_follow_up_questions,
    }
    event = serialize_case_response(event, terminal_stage=confirm_status)
    emit_node_event(trace_id, node="Persist", status="start", message="写入确认轮事件日志")
    try:
        append_event(serialize_final_response(event))
        emit_node_event(trace_id, node="Persist", status="end", message="确认轮事件落盘完成")
    except Exception as exc:
        print(f"Warning: failed to append confirm event: {exc}")
        emit_node_event(trace_id, node="Persist", status="error", message=f"确认轮事件落盘失败: {exc}")

    # Final 必须在 Persist 之后，才是真正终点
    emit_final_event_once(
        trace_id,
        status=confirm_status,
        message="二次诊断流程完成",
        payload={
            "final_disease": state.get("final_disease"),
            "confirm_round": True,
            "status": confirm_status,
        },
    )

    events = list_trace_events(trace_id)

    response_payload = {
        "trace_id": trace_id,
        "image_id": image_id,
        "final_disease": state.get("final_disease"),
        "image_result": image_result,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "image_confidence": image_confidence,
        "text_confidence": text_confidence,
        "text_top3": text_top3,
        "fusion_top3": fusion_top3,
        "modality_conflict_flag": modality_conflict_flag,
        "diagnosis_evidence": diagnosis_evidence,
        "manual_review_recommended": manual_review_recommended,
        "manual_review_required_before_execution": manual_review_required_before_execution,
        "status": confirm_status,
        "confirm_message": confirm_message,
        "treatment": None if manual_review_recommended else {
            "plan": state.get("treatment_plan"),
            "prevention": state.get("prevention_advice"),
        },
        "model_id": model_meta.get("model_id"),
        "model_display_name": model_meta.get("model_display_name"),
        "model_backend": model_meta.get("backend"),
        "resolved_model_path": model_meta.get("resolved_model_path"),
        "model_fallback_reason": model_meta.get("model_fallback_reason"),
        "personalization_applied": personalization_applied,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "follow_up_questions": follow_up_questions,
        "historical_follow_up_questions": historical_follow_up_questions,
        "missing_profile_fields": missing_profile_fields,
        "llm_failed": bool(flags.get("llm_failed")),
        "llm_failed_reason": flags.get("llm_failed_reason"),
        "verification_result": None if manual_review_recommended else state.get("verification_result"),
        "verification_passed": None if manual_review_recommended else state.get("verification_passed"),
        "verification_risk_level": None if manual_review_recommended else state.get("verification_risk_level"),
        "verification_issues": [] if manual_review_recommended else list(state.get("verification_issues") or []),
        "verification_summary": None if manual_review_recommended else state.get("verification_summary"),
        "treatment_available": bool(state.get("treatment_plan")) and not manual_review_recommended,
        "verification_available": (state.get("verification_result") is not None) and not manual_review_recommended,
        "graph_treatment_generated": bool(state.get("treatment_plan")),
        "fallback_treatment_used": False,
        "meta": response_meta,
        "events": events,
    }
    if previous_trace_id and previous_trace_id != trace_id:
        response_payload["previous_trace_id"] = previous_trace_id
    return serialize_final_response(response_payload)


@app.get("/api/models")
def get_models() -> dict[str, object]:
    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    return {"models": list_models(allow_torch=allow_torch)}


@app.get("/api/profiles")
def list_profiles() -> dict[str, list[dict[str, str | None]]]:
    profiles = []
    for farmer_id in list_profile_ids():
        path = get_profile_path(farmer_id)
        profile = load_profile(farmer_id)
        profiles.append({
            "id": farmer_id,
            "name": profile.name if profile else None,
            "path": str(path),
        })
    return {"profiles": profiles}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")




def _collect_existing_base_ids(exclude_farmer_id: str | None = None) -> dict[str, str]:
    """收集系统内已有基地ID -> 所属farmer_id（用于全局唯一校验）。"""
    result: dict[str, str] = {}
    for existing_farmer_id in list_profile_ids():
        if exclude_farmer_id and existing_farmer_id == exclude_farmer_id:
            continue
        profile = load_profile(existing_farmer_id)
        if not profile:
            continue
        for base_id in profile.bases.keys():
            result[base_id] = existing_farmer_id
    return result


@app.get("/api/profiles/base-ids")
def list_all_base_ids() -> dict[str, list[dict[str, str]]]:
    items = [
        {"base_id": base_id, "farmer_id": owner}
        for base_id, owner in sorted(_collect_existing_base_ids().items(), key=lambda item: (item[0], item[1]))
    ]
    return {"items": items}


def _normalize_profile_payload_for_save(farmer_id: str, payload: dict) -> FarmerProfile:
    """兼容前端旧结构并校验档案，确保可被 load_profile 解析。"""
    normalized = dict(payload)
    normalized["farmer_id"] = farmer_id

    bases = normalized.get("bases")
    if isinstance(bases, list):
        bases_map: dict[str, dict] = {}
        for item in bases:
            if not isinstance(item, dict):
                continue
            base_id = str(item.get("base_id") or "").strip()
            if not base_id:
                continue
            if base_id in bases_map:
                raise ValueError(f"同一农户下基地ID重复：{base_id}")
            base_data = dict(item)
            if "facility_type" in base_data and "facility" not in base_data:
                base_data["facility"] = base_data.pop("facility_type")
            if "growth_stage" in base_data:
                base_data["growth_stage"] = normalize_growth_stage(str(base_data.get("growth_stage") or ""))
            bases_map[base_id] = base_data
        normalized["bases"] = bases_map

    elif isinstance(bases, dict):
        checked: dict[str, dict] = {}
        for base_id, raw_base in bases.items():
            if base_id in checked:
                raise ValueError(f"同一农户下基地ID重复：{base_id}")
            base_data = dict(raw_base) if isinstance(raw_base, dict) else {}
            if "facility_type" in base_data and "facility" not in base_data:
                base_data["facility"] = base_data.pop("facility_type")
            if "growth_stage" in base_data:
                base_data["growth_stage"] = normalize_growth_stage(str(base_data.get("growth_stage") or ""))
            checked[str(base_id)] = base_data
        normalized["bases"] = checked

    profile = FarmerProfile.model_validate(normalized)

    existing_base_ids = _collect_existing_base_ids(exclude_farmer_id=farmer_id)
    for base_id in profile.bases.keys():
        owner = existing_base_ids.get(base_id)
        if owner:
            raise ValueError(f"基地ID已存在，请更换后再试（{base_id} 已归属 {owner}）")

    # 根据活跃基地播种日期自动估算采收窗口（旧字段兼容回退）。
    active_base = profile.bases.get(profile.active_base_id or "") if profile.active_base_id else None
    if active_base and active_base.sowing_date:
        estimated_days = estimate_harvest_window_days(active_base.sowing_date)
        if estimated_days is not None:
            profile.constraints.harvest_window_days = estimated_days

    profile.ensure_timestamp()
    profile.updated_at = _utc_now_iso()
    return profile


def _generate_farmer_id() -> str | None:
    """生成唯一的农户ID"""
    from personalization.profile_store import PROFILE_DIR
    
    if not PROFILE_DIR.exists():
        return "F0001"
    
    # 获取所有现有农户ID
    existing_ids = []
    for file in PROFILE_DIR.glob("*.json"):
        try:
            id = file.stem
            if id.startswith("F") and id[1:].isdigit():
                existing_ids.append(int(id[1:]))
        except:
            pass
    
    if not existing_ids:
        return "F0001"
    
    # 生成下一个ID
    next_id = max(existing_ids) + 1
    return f"F{next_id:04d}"


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
    for field in [
        "farm_scale",
        "pesticide_access_level",
        "equipment",
        "cultivation_mode",
        "experience_level",
        "risk_preference",
    ]:
        if field in payload:
            setattr(profile, field, payload.get(field))
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
    profile = load_profile(farmer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="档案不存在")
    return profile.model_dump()


@app.post("/api/profiles/{farmer_id}")
def save_profile_route(farmer_id: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="档案内容非法")
    try:
        profile = _normalize_profile_payload_for_save(farmer_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"档案格式非法: {exc}") from exc
    try:
        persist_profile(profile)
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


def _http_get_json(url: str) -> dict[str, Any] | None:
    try:
        with urlopen(url, timeout=8) as resp:  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def _pick_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@app.get("/api/location/reverse")
def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    # Nominatim/OpenStreetMap 免费逆地理编码
    from urllib.request import Request
    
    def _http_get_json_with_header(url: str) -> dict | None:
        try:
            req = Request(url, headers={"User-Agent": "tomato-diagnosis-dashboard/1.0"})
            with urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, dict) else None
        except Exception:
            return None
    
    params = urlencode({
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "addressdetails": 1,
        "accept-language": "zh-CN"
    })
    data = _http_get_json_with_header(f"https://nominatim.openstreetmap.org/reverse?{params}") or {}
    address = data.get("address") if isinstance(data.get("address"), dict) else {}

    province = str(
        address.get("state")
        or address.get("province")
        or address.get("region")
        or address.get("country_region")
        or address.get("administrative")
        or ""
    ).strip()
    
    # 对于直辖市，从城市名称中提取省份信息
    if not province and address.get("city"):
        city_name = str(address.get("city")).strip()
        if city_name in ["北京市", "上海市", "天津市", "重庆市"]:
            province = city_name

    city = str(
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("county")
        or ""
    ).strip()

    district = str(
        address.get("district")
        or address.get("county")
        or address.get("suburb")
        or ""
    ).strip()

    display_name = str(data.get("display_name") or "").strip()
    parts = [p for p in [province, city, district] if p]
    location = " ".join(parts).strip() or display_name

    return {
        "ok": bool(location),
        "latitude": lat,
        "longitude": lon,
        "province": province,
        "city": city,
        "district": district,
        "location": location,
        "raw_display_name": display_name,
    }


def _weather_code_to_cn(code: int | float | str | None) -> str:
    try:
        normalized = int(float(code))
    except Exception:
        return "天气情况未知"

    mapping = {
        0: "晴朗",
        1: "大部晴朗",
        2: "多云",
        3: "阴天",
        45: "有雾",
        48: "有雾凇",
        51: "小毛雨",
        53: "毛雨",
        55: "较强毛雨",
        56: "小冻毛雨",
        57: "冻毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "强冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "米雪",
        80: "阵雨",
        81: "较强阵雨",
        82: "强阵雨",
        85: "阵雪",
        86: "强阵雪",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }
    return mapping.get(normalized, "天气情况未知")


@app.get("/api/weather/summary")
def weather_summary(lat: float, lon: float) -> dict[str, Any]:
    # Open-Meteo 免费接口：更丰富但可降级的农业天气摘要。
    params = urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 2,
        "timezone": "auto",
    })
    data = _http_get_json(f"https://api.open-meteo.com/v1/forecast?{params}") or {}
    current = data.get("current") if isinstance(data.get("current"), dict) else {}
    daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}

    temp = current.get("temperature_2m")
    apparent_temperature = current.get("apparent_temperature")
    humidity = current.get("relative_humidity_2m")
    precipitation = current.get("precipitation")
    weather_code = current.get("weather_code")
    wind_speed_10m = current.get("wind_speed_10m")

    temperature_2m_max = None
    temperature_2m_min = None
    precipitation_probability_max = None

    max_list = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
    min_list = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
    rain_probs = daily.get("precipitation_probability_max") if isinstance(daily.get("precipitation_probability_max"), list) else []

    if max_list:
        temperature_2m_max = max_list[0]
    if min_list:
        temperature_2m_min = min_list[0]
    if rain_probs:
        try:
            precipitation_probability_max = max(float(v) for v in rain_probs[:2])
        except Exception:
            precipitation_probability_max = None

    rain_risk = precipitation_probability_max

    parts: list[str] = []
    weather_desc = _weather_code_to_cn(weather_code)
    if isinstance(temp, (int, float)):
        current_part = f"当前{weather_desc}，温度 {float(temp):.1f}℃"
        if isinstance(apparent_temperature, (int, float)):
            current_part += f"，体感 {float(apparent_temperature):.1f}℃"
        if isinstance(humidity, (int, float)):
            current_part += f"，湿度 {float(humidity):.0f}%"
        if isinstance(wind_speed_10m, (int, float)):
            current_part += f"，风速 {float(wind_speed_10m):.1f} m/s"
        parts.append(current_part)

    if isinstance(temperature_2m_max, (int, float)) and isinstance(temperature_2m_min, (int, float)):
        parts.append(f"今日最高/最低温约 {float(temperature_2m_max):.0f}℃ / {float(temperature_2m_min):.0f}℃")

    if isinstance(precipitation_probability_max, (int, float)):
        if precipitation_probability_max >= 60:
            rain_text = "未来24小时降雨概率较高"
        elif precipitation_probability_max >= 30:
            rain_text = "未来24小时降雨概率中等"
        else:
            rain_text = "未来24小时降雨概率较低"
        parts.append(rain_text)

    advisories: list[str] = []
    if isinstance(humidity, (int, float)) and float(humidity) >= 80:
        advisories.append("湿度偏高，注意真菌性病害传播风险")
    if isinstance(precipitation_probability_max, (int, float)) and float(precipitation_probability_max) >= 60:
        advisories.append("未来降雨概率较高，建议关注棚内排湿与叶面结露")
    if isinstance(precipitation, (int, float)) and float(precipitation) > 0:
        advisories.append("当前有降水，注意叶面湿润时段管理")

    summary_parts = (parts + advisories)[:4]
    summary = "。".join(summary_parts) if summary_parts else "天气数据暂不可用"

    return {
        "ok": summary != "天气数据暂不可用",
        "latitude": lat,
        "longitude": lon,
        "summary": summary,
        "temperature_2m": temp,
        "apparent_temperature": apparent_temperature,
        "relative_humidity_2m": humidity,
        "wind_speed_10m": wind_speed_10m,
        "weather_code": weather_code,
        "weather_desc": weather_desc,
        "precipitation": precipitation,
        "temperature_2m_max": temperature_2m_max,
        "temperature_2m_min": temperature_2m_min,
        "precipitation_probability_max": precipitation_probability_max,
        "rain_risk": rain_risk,
    }



@app.get("/api/events")
def get_events(start: str | None = None, end: str | None = None, limit: int = 50) -> dict[str, list[dict[str, Any]]]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return {"events": list_events_range(start, end, limit)}
    return {"events": list_events(limit)}




@app.get("/api/agents")
def list_agents_catalog() -> dict[str, object]:
    return {"agents": AGENTS_CATALOG, "node_to_agent": NODE_TO_AGENT}

@app.get("/api/traces/{trace_id}")
def get_trace(trace_id: str) -> dict[str, object]:
    events = list_trace_events(trace_id)
    return {"trace_id": trace_id, "events": events}


def _to_stream_event(trace_id: str, event: dict) -> dict:
    node = event.get("node") or event.get("agent") or "Trace"
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    agent_id = event.get("agent_id") or payload.get("agent_id") or NODE_TO_AGENT.get(node)
    if agent_id:
        payload = {**payload, "agent_id": agent_id}
    return {
        "trace_id": event.get("trace_id") or trace_id,
        "ts": event.get("ts"),
        "seq": event.get("seq"),
        "node": node,
        "agent_id": agent_id,
        "status": event.get("status") or event.get("step") or "info",
        "message": event.get("message") or event.get("step") or "",
        "payload": payload,
    }


@app.get("/api/traces/{trace_id}/stream")
async def stream_trace(trace_id: str):
    async def event_generator():
        queue = subscribe_trace(trace_id)
        try:
            history = list_trace_events(trace_id)
            for event in history:
                stream_event = _to_stream_event(trace_id, event)
                yield f"event: trace\ndata: {json.dumps(stream_event, ensure_ascii=False)}\n\n"
            while True:
                event = await queue.get()
                stream_event = _to_stream_event(trace_id, event)
                yield f"event: trace\ndata: {json.dumps(stream_event, ensure_ascii=False)}\n\n"
                if stream_event.get("node") == "Final" and stream_event.get("status") in {"end", "error"}:
                    break
                if stream_event.get("node") == "AwaitUserConfirmation" and stream_event.get("status") == "end":
                    break
        finally:
            unsubscribe_trace(trace_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/trace-events")
def get_trace_events(trace_id: str | None = None) -> dict[str, object]:
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id 不能为空")
    events = list_trace_events(trace_id)
    from trace_i18n import AGENT_NAME_CN, STEP_NAME_CN, REASON_CN
    enriched = []
    for event in events:
        agent = event.get("agent")
        step = event.get("step")
        decision = event.get("decision") or {}
        reasons = decision.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        reason_cn = [REASON_CN.get(reason, reason) for reason in reasons]
        enriched_event = dict(event)
        enriched_event["agent_cn"] = AGENT_NAME_CN.get(agent, agent)
        enriched_event["step_cn"] = STEP_NAME_CN.get(step, step)
        if decision:
            decision = dict(decision)
            decision["reasons_cn"] = reason_cn
            enriched_event["decision"] = decision
        enriched.append(enriched_event)
    return {
        "trace_id": trace_id,
        "events": enriched,
        "i18n": {
            "agent_name_cn": AGENT_NAME_CN,
            "step_name_cn": STEP_NAME_CN,
            "reason_cn": REASON_CN,
        },
    }


def validate_date_str(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _safe_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_branch(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().upper()
    if normalized in {"HOME", "FAMILY"}:
        return "FAMILY"
    if normalized in {"PRO", "MID"}:
        return "MID"
    if normalized == "ENTERPRISE":
        return "ENTERPRISE"
    return normalized


def _event_disease(event: dict[str, Any]) -> str:
    image_result = _safe_record(event.get("image_result"))
    return str(
        event.get("final_disease")
        or image_result.get("disease")
        or event.get("disease")
        or event.get("disease_name")
        or "未识别病害"
    ).strip() or "未识别病害"


def _event_model_id(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    return str(
        meta.get("model_id")
        or event.get("model_id")
        or ""
    ).strip()


def _event_model_label(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    return str(
        meta.get("model_display_name")
        or event.get("model_display_name")
        or _event_model_id(event)
        or "未知模型"
    ).strip() or "未知模型"


def _event_farmer_id(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    return str(meta.get("farmer_id") or event.get("farmer_id") or "").strip()


def _event_base_id(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    return str(meta.get("base_id") or event.get("base_id") or "").strip()


def _event_selected_branch(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    treatment = _safe_record(event.get("treatment"))
    outputs = _safe_record(event.get("outputs"))
    personalization = _safe_record(event.get("personalization"))
    personalization_outputs = _safe_record(event.get("personalization_outputs"))
    candidates = [
        event.get("selected_branch"),
        treatment.get("selected_branch"),
        outputs.get("selected_branch"),
        personalization.get("selected_branch"),
        personalization_outputs.get("selected_branch"),
        meta.get("selected_branch"),
        meta.get("branch"),
    ]
    for candidate in candidates:
        branch = _normalize_branch(candidate)
        if branch:
            return branch
    return ""


def _event_filtered(event: dict[str, Any]) -> bool:
    meta = _safe_record(event.get("meta"))
    return event.get("filtered") is True or meta.get("filtered") is True


def _event_filtered_reasons(event: dict[str, Any]) -> list[str]:
    meta = _safe_record(event.get("meta"))
    reasons = event.get("filtered_reasons")
    if not isinstance(reasons, list):
        reasons = meta.get("filtered_reasons")
    if not isinstance(reasons, list):
        return []
    return [str(reason).strip() for reason in reasons if str(reason).strip()]


def _event_personalization_applied(event: dict[str, Any]) -> bool:
    meta = _safe_record(event.get("meta"))
    return event.get("personalization_applied") is True or meta.get("personalization_applied") is True


def _event_degraded(event: dict[str, Any]) -> bool:
    meta = _safe_record(event.get("meta"))
    return (
        event.get("workflow_degraded") is True
        or meta.get("workflow_degraded") is True
        or event.get("llm_failed") is True
        or meta.get("llm_failed") is True
    )


def _event_llm_failed(event: dict[str, Any]) -> bool:
    meta = _safe_record(event.get("meta"))
    return event.get("llm_failed") is True or meta.get("llm_failed") is True


def _event_treatment_success(event: dict[str, Any]) -> bool:
    treatment = _safe_record(event.get("treatment"))
    plan = treatment.get("plan") or event.get("treatment_plan")
    return isinstance(plan, str) and bool(plan.strip())


def _event_elapsed_ms(event: dict[str, Any]) -> float | None:
    meta = _safe_record(event.get("meta"))
    timing = _safe_record(meta.get("timing"))

    def _parse_elapsed_value(raw: Any) -> float | None:
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value if value >= 0 else None
        if isinstance(raw, str):
            text = raw.strip().lower()
            if not text:
                return None
            compact = text.replace("毫秒", "ms").replace("秒", "s")
            match = re.search(r"-?\d+(?:\.\d+)?", compact)
            if not match:
                return None
            value = float(match.group(0))
            if value < 0:
                return None
            if compact.endswith("s") and not compact.endswith("ms"):
                value *= 1000
            return value
        return None

    def _walk_dict_for_elapsed(payload: dict[str, Any]) -> float | None:
        preferred_keys = (
            "elapsed_ms", "duration_ms", "latency_ms", "response_ms", "cost_ms",
            "elapsed", "duration", "latency", "response_time", "time_cost",
        )
        for key in preferred_keys:
            if key in payload:
                parsed = _parse_elapsed_value(payload.get(key))
                if parsed is not None:
                    return parsed
        for value in payload.values():
            if isinstance(value, dict):
                parsed = _walk_dict_for_elapsed(_safe_record(value))
                if parsed is not None:
                    return parsed
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        parsed = _walk_dict_for_elapsed(_safe_record(item))
                        if parsed is not None:
                            return parsed
        return None

    candidates = [
        event.get("elapsed_ms"),
        meta.get("elapsed_ms"),
        event.get("duration_ms"),
        meta.get("duration_ms"),
        event.get("latency_ms"),
        meta.get("latency_ms"),
        timing.get("elapsed_ms"),
        timing.get("duration_ms"),
        timing.get("latency_ms"),
    ]

    zero_fallback: float | None = None
    for candidate in candidates:
        parsed = _parse_elapsed_value(candidate)
        if parsed is None:
            continue
        if parsed > 0:
            return parsed
        zero_fallback = parsed

    from_nested = _walk_dict_for_elapsed(meta)
    if from_nested is not None:
        if from_nested > 0:
            return from_nested
        zero_fallback = from_nested if zero_fallback is None else zero_fallback

    from_event = _walk_dict_for_elapsed(event)
    if from_event is not None:
        if from_event > 0:
            return from_event
        zero_fallback = from_event if zero_fallback is None else zero_fallback

    return zero_fallback


def _event_in_filters(
    event: dict[str, Any],
    farmer_id: str | None,
    base_id: str | None,
    disease: str | None,
    model_id: str | None,
    selected_branch: str | None,
    personalization_status: str | None,
) -> bool:
    if farmer_id and farmer_id != "ALL" and _event_farmer_id(event) != farmer_id:
        return False
    if base_id and base_id != "ALL" and _event_base_id(event) != base_id:
        return False
    if disease and disease != "ALL" and _event_disease(event) != disease:
        return False
    if model_id and model_id != "ALL" and _event_model_id(event) != model_id:
        return False
    if selected_branch and selected_branch != "ALL" and _event_selected_branch(event) != _normalize_branch(selected_branch):
        return False
    if personalization_status == "APPLIED" and not _event_personalization_applied(event):
        return False
    if personalization_status == "FILTERED" and not _event_filtered(event):
        return False
    return True


def _load_filtered_events(
    start: str | None,
    end: str | None,
    farmer_id: str | None,
    base_id: str | None,
    disease: str | None,
    model_id: str | None,
    selected_branch: str | None,
    personalization_status: str | None,
) -> list[dict[str, Any]]:
    events = list_events_range(start, end, 200000) if (start or end) else list_events(200000)
    return [
        event for event in events
        if _event_in_filters(event, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
    ]


@app.get("/api/stats/disease")
def get_disease_stats(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    safe_days = max(1, min(3650, int(days)))
    if any([farmer_id, base_id, disease, model_id, selected_branch, personalization_status]):
        events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
        counts: dict[str, int] = {}
        for event in events:
            disease_name = _event_disease(event)
            counts[disease_name] = counts.get(disease_name, 0) + 1
    else:
        counts = stats_by_disease_range(start, end) if (start or end) else stats_by_disease(safe_days)
    items = [{"disease": disease_name, "count": count} for disease_name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]
    return {"items": items}


@app.get("/api/stats/timeseries")
def get_timeseries(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    if any([farmer_id, base_id, disease, model_id, selected_branch, personalization_status]):
        events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
        counts: dict[str, int] = {}
        for event in events:
            ts = event.get("ts")
            if not isinstance(ts, str):
                continue
            day = ts.split("T", 1)[0]
            counts[day] = counts.get(day, 0) + 1
        items = [{"date": day, "count": counts[day]} for day in sorted(counts.keys())]
        return {"items": items}
    if start or end:
        return {"items": timeseries_range(start, end)}
    safe_days = max(1, min(3650, int(days)))
    return {"items": timeseries(safe_days)}


@app.get("/api/stats/geo")
def get_geo_stats(
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return {"items": geo_points_range(start, end)}
    safe_days = max(1, min(3650, int(days)))
    return {"items": geo_points(safe_days)}


@app.get("/api/stats/models")
def get_model_stats(
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
    if not events and not any([farmer_id, base_id, disease, model_id, selected_branch, personalization_status]):
        raw_counts = model_usage_range(start, end)
        return {
            "items": [{"model": model, "count": count, "success": count, "fallback": 0, "degraded": 0, "llm_failed_rate": 0.0, "avg_response_ms": 0.0} for model, count in raw_counts.items()],
        }

    aggregates: dict[str, dict[str, float]] = {}
    for event in events:
        label = _event_model_label(event)
        item = aggregates.setdefault(label, {"count": 0, "success": 0, "fallback": 0, "degraded": 0, "llm_failed": 0, "elapsed_sum": 0, "elapsed_count": 0})
        item["count"] += 1
        if _event_degraded(event):
            item["degraded"] += 1
        elif str(event.get("final_source") or "").strip().lower() in {"rule", "fallback"}:
            item["fallback"] += 1
        else:
            item["success"] += 1
        if _event_llm_failed(event):
            item["llm_failed"] += 1
        elapsed_ms = _event_elapsed_ms(event)
        if elapsed_ms is not None:
            item["elapsed_sum"] += elapsed_ms
            item["elapsed_count"] += 1

    items = []
    for model, value in aggregates.items():
        count = int(value["count"])
        items.append({
            "model": model,
            "count": count,
            "success": int(value["success"]),
            "fallback": int(value["fallback"]),
            "degraded": int(value["degraded"]),
            "llm_failed_rate": (value["llm_failed"] / count * 100) if count > 0 else 0.0,
            "avg_response_ms": (value["elapsed_sum"] / value["elapsed_count"]) if value["elapsed_count"] > 0 else 0.0,
        })
    items.sort(key=lambda item: item["count"], reverse=True)
    return {"items": items[:8]}


@app.get("/api/stats/summary")
def get_stats_summary(
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, float | int]:
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
    total = len(events)
    today = datetime.now(timezone.utc).date().isoformat()
    today_count = 0
    disease_set = set()
    first_pass_done = 0
    treatment_success = 0
    filtered_count = 0
    degraded_count = 0
    llm_failed_count = 0
    elapsed_values: list[float] = []

    for event in events:
        ts = event.get("ts")
        ts_date = str(ts).split("T", 1)[0] if isinstance(ts, str) else ""
        if ts_date == today:
            today_count += 1
        disease_set.add(_event_disease(event))
        confirm_round = event.get("confirm_round") is True
        need_confirm = event.get("need_confirm") is True
        if not confirm_round and not need_confirm:
            first_pass_done += 1
        if _event_treatment_success(event):
            treatment_success += 1
        if _event_filtered(event):
            filtered_count += 1
        if _event_degraded(event):
            degraded_count += 1
        if _event_llm_failed(event):
            llm_failed_count += 1
        elapsed_ms = _event_elapsed_ms(event)
        if elapsed_ms is not None:
            elapsed_values.append(elapsed_ms)

    return {
        "total": total,
        "today": today_count,
        "disease_kinds": len(disease_set),
        "first_pass_rate": (first_pass_done / total * 100) if total > 0 else 0.0,
        "treatment_success_rate": (treatment_success / total * 100) if total > 0 else 0.0,
        "filtered_rate": (filtered_count / total * 100) if total > 0 else 0.0,
        "degraded_rate": (degraded_count / total * 100) if total > 0 else 0.0,
        "llm_failed_rate": (llm_failed_count / total * 100) if total > 0 else 0.0,
        "avg_response_ms": (sum(elapsed_values) / len(elapsed_values)) if elapsed_values else 0.0,
    }


@app.get("/api/stats/filter-reasons")
def get_filter_reasons_stats(
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
    counts: dict[str, int] = {}
    for event in events:
        for reason in _event_filtered_reasons(event):
            counts[reason] = counts.get(reason, 0) + 1
    items = [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]
    return {"items": items}


@app.get("/api/stats/by-farmer")
def get_stats_by_farmer(
    start: str | None = None,
    end: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, None, base_id, disease, model_id, selected_branch, personalization_status)
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        farmer_id = _event_farmer_id(event) or "未绑定农户"
        meta = _safe_record(event.get("meta"))
        item = grouped.setdefault(farmer_id, {"farmer_id": farmer_id, "farmer_name": str(meta.get("farmer_name") or meta.get("name") or ""), "count": 0, "filtered": 0, "degraded": 0, "confirm_round": 0})
        item["count"] += 1
        if _event_filtered(event):
            item["filtered"] += 1
        if _event_degraded(event):
            item["degraded"] += 1
        if event.get("confirm_round") is True:
            item["confirm_round"] += 1

    items = []
    for value in grouped.values():
        total = value["count"]
        items.append({
            "farmer_id": value["farmer_id"],
            "farmer_name": value["farmer_name"],
            "count": total,
            "filtered_rate": value["filtered"] / total * 100 if total else 0,
            "degraded_rate": value["degraded"] / total * 100 if total else 0,
            "confirm_round_rate": value["confirm_round"] / total * 100 if total else 0,
        })
    items.sort(key=lambda item: item["count"], reverse=True)
    return {"items": items[:8]}


@app.get("/api/stats/by-base")
def get_stats_by_base(
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
) -> dict[str, Any]:
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, None, None, model_id, selected_branch, personalization_status)
    grouped: dict[str, dict[str, Any]] = {}
    all_diseases: dict[str, int] = {}
    for event in events:
        base_id = _event_base_id(event) or "未绑定基地"
        meta = _safe_record(event.get("meta"))
        disease = _event_disease(event)
        all_diseases[disease] = all_diseases.get(disease, 0) + 1
        item = grouped.setdefault(base_id, {"base_id": base_id, "base_name": str(meta.get("base_name") or ""), "count": 0, "disease_counts": {}})
        item["count"] += 1
        disease_counts = item["disease_counts"]
        disease_counts[disease] = disease_counts.get(disease, 0) + 1

    top_diseases = [name for name, _ in sorted(all_diseases.items(), key=lambda pair: pair[1], reverse=True)[:4]]
    items = []
    for value in grouped.values():
        disease_counts = value["disease_counts"]
        filtered_counts = {name: disease_counts.get(name, 0) for name in top_diseases}
        others = max(value["count"] - sum(filtered_counts.values()), 0)
        if others > 0:
            filtered_counts["其他"] = others
        items.append({
            "base_id": value["base_id"],
            "base_name": value["base_name"],
            "count": value["count"],
            "disease_counts": filtered_counts,
        })
    items.sort(key=lambda item: item["count"], reverse=True)
    return {"top_diseases": top_diseases + (["其他"] if any("其他" in item["disease_counts"] for item in items) else []), "items": items[:6]}


@app.get("/dashboard")
def get_dashboard() -> Response:
    return serve_frontend_index()


@app.get("/profiles")
def get_profiles_page() -> Response:
    return serve_frontend_index()


@app.get("/kb")
def get_kb_page() -> Response:
    return serve_frontend_index()


@app.get("/kb/{name:path}")
def get_kb_detail_page(name: str) -> Response:
    if not name.strip():
        raise HTTPException(status_code=404, detail="Not Found")
    return serve_frontend_index()


@app.get("/api/kb/diseases")
def list_kb_diseases() -> dict:
    return {"items": kb.list_diseases()}


@app.get("/api/kb/diseases/{name}")
def get_kb_disease_detail(name: str) -> dict:
    target_name = name.strip()
    diseases = {item["name"]: item for item in kb.list_diseases()}
    if target_name not in diseases:
        raise HTTPException(status_code=404, detail="病害不存在")
    detail = diseases[target_name]
    plan = kb.get_treatment_plan(target_name) or {}
    return {
        "name": target_name,
        "description": detail.get("description", ""),
        "treatment": plan.get("treatment", ""),
        "prevention": plan.get("prevention", ""),
        "actions": plan.get("actions") if isinstance(plan.get("actions"), dict) else None,
        "ingredients": plan.get("ingredients") if isinstance(plan.get("ingredients"), list) else [],
    }


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
        raise HTTPException(status_code=409, detail="病害已存在，请使用更新功能")
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
    actions = payload.get("actions") if isinstance(payload.get("actions"), dict) else None
    ingredients = payload.get("ingredients") if isinstance(payload.get("ingredients"), list) else None
    if not disease or not treatment or not prevention:
        raise HTTPException(status_code=400, detail="病害、治疗与预防不能为空")
    existing = {item["disease"] for item in kb.list_treatments()}
    if disease in existing:
        raise HTTPException(status_code=409, detail="治疗方案已存在，请使用编辑")
    kb.upsert_treatment_plan(disease, treatment, prevention, actions=actions, ingredients=ingredients)
    return {"ok": True}


@app.put("/api/kb/treatments/{disease}")
def update_kb_treatments(disease: str, payload: dict = Body(...)) -> dict[str, bool]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    treatment = (payload.get("treatment") or "").strip()
    prevention = (payload.get("prevention") or "").strip()
    actions = payload.get("actions") if isinstance(payload.get("actions"), dict) else None
    ingredients = payload.get("ingredients") if isinstance(payload.get("ingredients"), list) else None
    if not treatment or not prevention:
        raise HTTPException(status_code=400, detail="治疗与预防不能为空")
    existing = {item["disease"] for item in kb.list_treatments()}
    if disease not in existing:
        raise HTTPException(status_code=404, detail="治疗方案不存在")
    kb.update_treatment(disease, treatment=treatment, prevention=prevention, actions=actions, ingredients=ingredients)
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


if FRONTEND_DIR.exists():
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    # 启动示例：uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    pass
