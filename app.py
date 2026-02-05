from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import DIAGNOSIS_CONFIDENCE_THRESHOLD
from diagnosis_model import get_diagnosis_engine


app = FastAPI(title="Tomato Diagnosis API", version="1.0.0")
UPLOAD_DIR = Path(".cache/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
WEB_DIR = Path("web")

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


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
        saved_path.write_bytes(data)
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
    }


if __name__ == "__main__":
    # 启动示例：uvicorn app:app --host 0.0.0.0 --port 8000 --reload
    pass
