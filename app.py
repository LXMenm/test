from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from config import DIAGNOSIS_CONFIDENCE_THRESHOLD
from diagnosis_model import get_diagnosis_engine
from knowledge_base import get_kb_manager


app = FastAPI(title="Tomato Diagnosis API", version="1.0.0")
kb = get_kb_manager()
UPLOAD_DIR = Path(".cache/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WEB_DIR = Path("web")

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


@app.post("/api/diagnose-image")
async def diagnose_image(
    file: UploadFile = File(...),
    crop_type: str = Form("番茄"),
    symptoms: str | None = Form(None),
    growth_stage: str | None = Form(None),
) -> dict[str, Any]:
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
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="上传文件超过8MB限制")

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

    if disease == "模型未加载":
        raise HTTPException(status_code=500, detail="模型未加载，请先配置并加载模型")
    if probs is None:
        probs = {}

    top3_pairs = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:3]
    top3 = [{"disease": name, "prob": float(prob)} for name, prob in top3_pairs]

    symptoms_list = [s.strip() for s in (symptoms or "").split(",") if s.strip()]
    fallback_condition = (
        disease == "疑似病害（置信度不足）" or float(conf) < DIAGNOSIS_CONFIDENCE_THRESHOLD
    )

    fallback_used = False
    rule_result: dict[str, Any] | None = None

    if fallback_condition and symptoms_list:
        try:
            rule_disease, rule_confidence, rule_description = engine.diagnose_from_symptoms(
                crop_type=crop_type,
                symptoms=symptoms_list,
                growth_stage=growth_stage,
            )
            fallback_used = True
            rule_result = {
                "rule_disease": rule_disease,
                "rule_confidence": float(rule_confidence),
                "rule_description": rule_description,
            }
        except Exception as exc:
            rule_result = {
                "rule_disease": None,
                "rule_confidence": 0.0,
                "rule_description": f"症状回退诊断失败: {exc}",
            }
            fallback_used = True

    final_disease = disease
    if fallback_used and rule_result and rule_result.get("rule_disease"):
        final_disease = rule_result["rule_disease"]

    treatment = None
    if final_disease:
        plan = kb.get_treatment_plan(final_disease)
        if isinstance(plan, dict) and "treatment" in plan and "prevention" in plan:
            treatment = {
                "plan": plan["treatment"],
                "prevention": plan["prevention"],
            }

    return {
        "image_id": unique_name,
        "image_url": f"/uploads/{unique_name}",
        "image_result": {
            "disease": disease,
            "confidence": float(conf),
            "top3": top3,
        },
        "fallback_used": fallback_used,
        "rule_result": rule_result,
        "final_disease": final_disease,
        "treatment": treatment,
    }


if __name__ == "__main__":
    # 启动示例：uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    pass
