from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
import os
import re
import subprocess
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
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
from sqlalchemy import select

from config import DIAGNOSIS_ALLOW_TORCH, PROFILE_STORE_MODE, log_resolved_storage_config
from diagnosis_model import get_diagnosis_engine
import diagnosis_model as diagnosis_model_module
import agents as agents_module
import knowledge_base.kb_manager as kb_manager_module
from agents import append_trace, diagnosis_agent, kb_retrieval_agent, treatment_agent, verification_agent, supervisor_agent
from event_store import (
    append_event,
    get_latest_event_by_trace,
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
from personalization.profile_store import (
    delete_profile as delete_profile_store,
    get_profile_path,
    load_profile,
    list_profile_ids,
    save_profile as persist_profile,
)
from repositories.profile_repo_mysql import (
    get_profile as get_profile_mysql,
    list_profile_ids as list_profile_ids_mysql,
    save_profile_payload as save_profile_payload_mysql,
)
from repositories.weather_repo_mysql import (
    list_weather_snapshots_mysql,
    upsert_weather_snapshot_mysql,
)
from personalization.utils import dedupe_reasons, compute_personalization_applied, normalize_follow_up_questions
from state import create_initial_state
from trace_store import list_trace_events, subscribe as subscribe_trace, unsubscribe as unsubscribe_trace, emit_trace_event
from model_registry import list_models, resolve_model
from workflow import build_graph
from trace_catalog import AGENTS_CATALOG, NODE_TO_AGENT
from runtime_settings import get_admin_llm_runtime_snapshot, get_runtime_thresholds, load_admin_runtime_config, save_admin_runtime_config
from db import engine as db_engine, get_db_session
from mysql_models import FarmerProfileORM, UserAccountORM


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_resolved_storage_config()
    demo_accounts_enabled = os.getenv("ENABLE_DEMO_ACCOUNTS", "false").strip().lower() in {"1", "true", "yes", "on"}
    print(f"[DemoAccounts] ENABLE_DEMO_ACCOUNTS={'true' if demo_accounts_enabled else 'false'}")
    if demo_accounts_enabled:
        ensure_user_accounts_seeded()
    ensure_account_profile_consistency()
    yield


app = FastAPI(title="Tomato Diagnosis API", version="1.0.0", lifespan=lifespan)

SUPPORTED_ROLES = {"USER", "EXPERT", "ADMIN"}
DEFAULT_DEMO_ACCOUNTS = [
    {"user_id": "F0001", "username": "f0001", "display_name": "农户 F0001", "role": "USER", "password": "123456", "linked_farmer_id": "F0001"},
    {"user_id": "F0002", "username": "f0002", "display_name": "农户 F0002", "role": "USER", "password": "123456", "linked_farmer_id": "F0002"},
    {"user_id": "E0001", "username": "e0001", "display_name": "专家 E0001", "role": "EXPERT", "password": "123456", "linked_farmer_id": None},
    {"user_id": "E0002", "username": "e0002", "display_name": "专家 E0002", "role": "EXPERT", "password": "123456", "linked_farmer_id": None},
    {"user_id": "A0001", "username": "a0001", "display_name": "管理员 A0001", "role": "ADMIN", "password": "123456", "linked_farmer_id": None},
]
# linked_farmer_id 为兼容字段：一账号一档案阶段默认应与 user_id 相同，不再用于切换他人档案。


def _generate_user_id() -> str | None:
    """预留统一账号ID生成策略：新账号统一 FXXXX；权限只看 role，不看前缀。"""
    try:
        with get_db_session() as session:
            existing_ids = []
            rows = session.execute(select(UserAccountORM.user_id)).all()
            for row in rows:
                user_id = str(row[0] or "").strip().upper() if row else ""
                if user_id.startswith("F") and user_id[1:].isdigit():
                    existing_ids.append(int(user_id[1:]))
            next_no = (max(existing_ids) + 1) if existing_ids else 1
            return f"F{next_no:04d}"
    except Exception:
        return None


def ensure_user_accounts_seeded() -> None:
    try:
        UserAccountORM.__table__.create(bind=db_engine, checkfirst=True)
        FarmerProfileORM.__table__.create(bind=db_engine, checkfirst=True)
        with get_db_session() as session:
            existing = {
                str(item.user_id).strip()
                for item in session.execute(select(UserAccountORM.user_id)).all()
                if item and item[0]
            }
            changed = False
            for account in DEFAULT_DEMO_ACCOUNTS:
                if account["user_id"] in existing:
                    continue
                session.add(UserAccountORM(**account, status="ACTIVE"))
                changed = True
            if changed:
                session.commit()
    except Exception as exc:
        print(f"[AuthBootstrap] 初始化 user_accounts 失败: {exc}")


def ensure_account_profile_consistency() -> None:
    """一账号一档案收敛：确保每个账号有且仅有自己 user_id 对应档案（farmer_id=user_id, owner_user_id=user_id）。"""
    try:
        with get_db_session() as session:
            accounts = session.execute(select(UserAccountORM).order_by(UserAccountORM.user_id.asc())).scalars().all()
            dirty = False
            for account in accounts:
                user_id = str(account.user_id or "").strip()
                if not user_id:
                    continue
                profile = load_profile(user_id)
                if profile is None:
                    profile = FarmerProfile(
                        farmer_id=user_id,
                        name=account.display_name,
                        display_name=account.display_name,
                        owner_user_id=user_id,
                        role_type="FARMER",
                    )
                    persist_profile(profile)
                else:
                    changed = False
                    if str(profile.owner_user_id or "").strip() != user_id:
                        profile.owner_user_id = user_id
                        changed = True
                    if changed:
                        profile.ensure_timestamp()
                        persist_profile(profile)
                if str(account.linked_farmer_id or "").strip() != user_id:
                    account.linked_farmer_id = user_id
                    dirty = True
            if dirty:
                session.commit()
    except Exception as exc:
        print(f"[AuthBootstrap] 一账号一档案对齐失败: {exc}")


def _get_request_actor(request: Request | None) -> dict[str, str]:
    headers = request.headers if request is not None else {}
    user_id = str(headers.get("X-User-Id") or "").strip()
    raw_role = str(headers.get("X-User-Role") or "USER").strip().upper()
    linked_farmer_id = str(headers.get("X-Linked-Farmer-Id") or "").strip()
    role = raw_role if raw_role in SUPPORTED_ROLES else "USER"
    return {
        "user_id": user_id,
        "role": role,
        "linked_farmer_id": linked_farmer_id,
    }


def _is_admin(actor: dict[str, str]) -> bool:
    return actor.get("role") == "ADMIN"


def _is_expert(actor: dict[str, str]) -> bool:
    return actor.get("role") in {"EXPERT", "ADMIN"}


def _apply_farmer_scope(actor: dict[str, str], requested_farmer_id: str | None) -> str | None:
    if _is_admin(actor):
        return requested_farmer_id
    actor_user_id = str(actor.get("user_id") or "").strip()
    if not actor_user_id:
        return requested_farmer_id
    requested = str(requested_farmer_id or "").strip()
    if requested and requested != actor_user_id:
        raise HTTPException(status_code=403, detail="当前角色仅允许访问自己的数据")
    return actor_user_id


def _resolve_default_profile_id(
    actor: dict[str, str],
    requested_farmer_id: str | None = None,
) -> str | None:
    """兼容函数：保留显式 farmer_id 解析，不再支持通过 linked_farmer_id 切换他人档案。"""
    _ = actor
    requested = str(requested_farmer_id or "").strip() or None
    return requested


def _validate_account_exists(session, user_id: str) -> UserAccountORM:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise HTTPException(status_code=400, detail="绑定账号不存在")
    account = session.execute(
        select(UserAccountORM).where(UserAccountORM.user_id == normalized_user_id)
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=400, detail="绑定账号不存在")
    if str(account.status or "").strip().upper() != "ACTIVE":
        raise HTTPException(status_code=400, detail="绑定账号不是激活状态")
    return account


def _next_generated_user_id(session) -> str:
    existing_ids: list[int] = []
    rows = session.execute(select(UserAccountORM.user_id)).all()
    for row in rows:
        user_id = str(row[0] or "").strip().upper() if row else ""
        if user_id.startswith("F") and user_id[1:].isdigit():
            existing_ids.append(int(user_id[1:]))
    next_no = (max(existing_ids) + 1) if existing_ids else 1
    return f"F{next_no:04d}"


def _create_account_with_profile(
    session,
    *,
    username: str,
    display_name: str,
    password: str,
    role: str | None = "USER",
) -> tuple[UserAccountORM, FarmerProfileORM]:
    normalized_username = str(username or "").strip()
    normalized_display_name = str(display_name or "").strip()
    normalized_password = str(password or "").strip()
    normalized_role = str(role or "USER").strip().upper() or "USER"

    if not normalized_username:
        raise HTTPException(status_code=400, detail="username 不能为空")
    if not normalized_display_name:
        raise HTTPException(status_code=400, detail="display_name 不能为空")
    if not normalized_password:
        raise HTTPException(status_code=400, detail="password 不能为空")
    if normalized_role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=400, detail="非法角色类型")

    existing_user = session.execute(
        select(UserAccountORM).where(UserAccountORM.username == normalized_username)
    ).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user_id = _next_generated_user_id(session)
    existing_profile = session.execute(
        select(FarmerProfileORM).where(FarmerProfileORM.owner_user_id == user_id)
    ).scalar_one_or_none()
    if existing_profile is not None:
        raise HTTPException(status_code=409, detail="账号档案冲突，请稍后重试")

    account = UserAccountORM(
        user_id=user_id,
        username=normalized_username,
        display_name=normalized_display_name,
        role=normalized_role,
        password=normalized_password,
        linked_farmer_id=user_id,
        status="ACTIVE",
    )
    profile = FarmerProfileORM(
        farmer_id=user_id,
        name=normalized_display_name,
        display_name=normalized_display_name,
        owner_user_id=user_id,
        # role_type 兼容保留（已废弃，不承载身份语义）。
        role_type="FARMER",
    )
    session.add(account)
    session.add(profile)
    return account, profile


def _serialize_account_sync(account: UserAccountORM) -> dict[str, Any]:
    return {
        "user_id": account.user_id,
        "role": str(account.role or "USER").upper(),
        "linked_farmer_id": account.linked_farmer_id,
    }


def _require_admin(actor: dict[str, str], message: str = "当前操作仅管理员可执行") -> None:
    if not _is_admin(actor):
        raise HTTPException(status_code=403, detail=message)


def _require_expert(actor: dict[str, str], message: str = "当前操作仅专家可执行") -> None:
    if not _is_expert(actor):
        raise HTTPException(status_code=403, detail=message)


class _LazyKBProxy:
    def __getattr__(self, item: str):
        return getattr(get_kb_manager(), item)


kb = _LazyKBProxy()
IMAGE_UPLOAD_DIR = os.getenv("IMAGE_UPLOAD_DIR", "data/uploads")
IMAGE_UPLOAD_TTL_HOURS = int(os.getenv("IMAGE_UPLOAD_TTL_HOURS", "0") or "0")
UPLOAD_DIR = Path(IMAGE_UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
FRONTEND_DIR = Path("app/dist")
LEGACY_WEB_DIR = Path("web")
MAX_UPLOAD_MB = 8


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
    confirm_reasons: list[str] = []
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
    llm_failed_reason: str | None = None
    trace_id: str
    need_confirm: bool | None = None
    final_confidence: float | None = None
    final_source: str | None = None
    fusion_mode: str | None = None
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
    image_reliable: bool | None = None
    text_reliable: bool | None = None
    reliability_issue_types: list[str] = []
    supplement_mode: str = "none"
    normalized_symptoms: list[str] = []
    debug_runtime: dict[str, Any] | None = None
    verification_result: dict[str, Any] | None = None
    verification_passed: bool | None = None
    verification_risk_level: str | None = None
    verification_issues: list[str] = []
    verification_summary: str | None = None
    status: str = "completed"
    expert_review_recommended: bool = False
    expert_review_selected: bool = False
    expert_review_status: str = "NONE"
    expert_review_actions: list[str] = []
    confirm_message: str | None = None
    treatment_skipped_due_need_confirm: bool = False
    treatment_available: bool = False
    verification_available: bool = False
    manual_review_recommended: bool = False
    graph_treatment_generated: bool = False
    fallback_treatment_used: bool = False
    manual_review_required_before_execution: bool = False
    confirm_round_parent_trace_id: str | None = None
    meta: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []


class LoginRequest(BaseModel):
    user_id: str
    password: str | None = None


class AdminCreateAccountRequest(BaseModel):
    username: str
    display_name: str
    password: str
    role: str = "USER"


class AdminUpdateAccountRoleRequest(BaseModel):
    role: str


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
    return normalized or text


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
    "confirm_reasons",
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
        str(item).strip().strip("。.;；,，")
        for item in _as_clean_list(payload.get("model_fallback_reason"))
        if str(item).strip().strip("。.;；,，")
    ]

    return payload


def _normalize_reason_codes(value: Any) -> list[str]:
    return [
        str(item).strip().strip("。.;；,，")
        for item in _as_clean_list(value)
        if str(item).strip().strip("。.;；,，")
    ]


def _is_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


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

    # canonical 统一进 meta，root 保持兼容性非空回填
    for key in META_ONLY_CANONICAL_KEYS:
        if _is_non_empty_value(data.get(key)) and not _is_non_empty_value(meta.get(key)):
            meta[key] = data[key]

    if meta:
        data["meta"] = _normalize_meta_payload(meta)
        normalized_meta = dict(data["meta"] or {})
        for key in META_ONLY_CANONICAL_KEYS:
            if not _is_non_empty_value(data.get(key)) and _is_non_empty_value(normalized_meta.get(key)):
                data[key] = normalized_meta.get(key)

    for key in LIST_FIELDS_ALWAYS:
        data[key] = _as_clean_list(data.get(key))

    if "fallback_reason" in data:
        reasons = _normalize_reason_codes(data.get("fallback_reason"))
        data["fallback_reason"] = reasons or None
    if "confirm_reasons" in data:
        data["confirm_reasons"] = _normalize_reason_codes(data.get("confirm_reasons"))

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

    return data


def _compact_trace_steps(trace_id: str | None) -> list[dict[str, Any]]:
    normalized_trace_id = str(trace_id or "").strip()
    if not normalized_trace_id:
        return []

    steps: list[dict[str, Any]] = []
    try:
        events = list_trace_events(normalized_trace_id)
    except Exception:
        return []

    for event in events:
        if not isinstance(event, dict):
            continue
        payload = _safe_record(event.get("payload"))
        steps.append(
            {
                "seq": event.get("seq"),
                "node": event.get("node") or event.get("agent") or payload.get("agent_id"),
                "agent_id": event.get("agent_id") or payload.get("agent_id"),
                "status": event.get("status"),
                "message": event.get("message"),
                "ts": event.get("ts"),
            }
        )
    return steps


def _serialize_event_dto(payload: dict[str, Any], *, inject_trace_steps: bool = False) -> dict[str, Any]:
    data = serialize_final_response(payload)
    if inject_trace_steps:
        trace_steps = _compact_trace_steps(data.get("trace_id"))
        if trace_steps:
            data["trace_steps"] = trace_steps
            if not isinstance(data.get("trace_events"), list) or not data.get("trace_events"):
                data["trace_events"] = trace_steps
    return data


def _derive_fusion_mode(final_source: Any, diagnosis_evidence: Any) -> str | None:
    if str(final_source or "").strip().lower() != "fusion":
        return None
    evidence = _safe_record(diagnosis_evidence)
    weights = _safe_record(evidence.get("weights"))
    image_weight = _safe_float(weights.get("image"))
    text_weight = _safe_float(weights.get("text"))
    prior_weight = _safe_float(weights.get("prior"))
    if image_weight is None and text_weight is None:
        return None
    image_weight = float(image_weight or 0.0)
    text_weight = float(text_weight or 0.0)
    prior_weight = float(prior_weight or 0.0)
    if image_weight >= 0.999 and text_weight <= 0.001 and prior_weight <= 0.001:
        return "gated_image_only"
    if text_weight >= 0.999 and image_weight <= 0.001 and prior_weight <= 0.001:
        return "gated_text_only"
    return "blended"


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


TERMINAL_CASE_STATUSES = {"completed", "pending_expert_review", "manual_review_recommended", "failed", "cancelled"}


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


def cleanup_old_uploads(max_age_hours: int | None = None) -> None:
    resolved_max_age_hours = IMAGE_UPLOAD_TTL_HOURS if max_age_hours is None else max_age_hours
    if resolved_max_age_hours <= 0:
        return

    now_ts = __import__("time").time()
    max_age_seconds = resolved_max_age_hours * 3600
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


def _latest_case_event_by_trace(trace_id: str) -> dict[str, Any]:
    event = get_latest_event_by_trace(trace_id)
    return event if isinstance(event, dict) else {}


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_top3_candidates(value: Any) -> list[tuple[str, float]]:
    normalized: list[tuple[str, float]] = []
    for item in _as_clean_list(value):
        disease = ""
        prob: float | None = None
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            disease = str(item[0]).strip()
            prob = _safe_float(item[1])
        elif isinstance(item, dict):
            disease = str(
                item.get("disease")
                or item.get("label")
                or item.get("name")
                or ""
            ).strip()
            prob = _safe_float(item.get("prob"))
            if prob is None:
                prob_pct = _safe_float(item.get("prob_pct"))
                prob = (prob_pct / 100.0) if prob_pct is not None else None
            if prob is None:
                prob = _safe_float(item.get("confidence"))
            if prob is None:
                confidence_pct = _safe_float(item.get("confidence_pct"))
                prob = (confidence_pct / 100.0) if confidence_pct is not None else None
        if disease and prob is not None:
            normalized.append((disease, float(prob)))
    return normalized


def _build_image_diagnosis_from_event(event: dict[str, Any]) -> dict[str, Any]:
    image_result = _safe_record(event.get("image_result"))
    top3 = _normalize_top3_candidates(image_result.get("top3"))
    top1_disease = str(image_result.get("disease") or "").strip()
    top1_confidence = _safe_float(image_result.get("confidence"))
    if top1_confidence is None:
        confidence_pct = _safe_float(image_result.get("confidence_pct"))
        top1_confidence = (confidence_pct / 100.0) if confidence_pct is not None else None

    if not top3 and top1_disease and top1_confidence is not None:
        top3 = [(top1_disease, top1_confidence)]
    if (not top1_disease or top1_confidence is None) and top3:
        top1_disease, top1_confidence = top3[0]

    if not top1_disease and not top3:
        return {}

    return {
        "top1": {
            "disease": top1_disease,
            "confidence": float(top1_confidence or 0.0),
        },
        "top3": [(name, float(prob)) for name, prob in top3],
    }


def _extract_event_model_meta(event: dict[str, Any]) -> dict[str, Any]:
    meta = _safe_record(event.get("meta"))
    fallback_reason = [
        str(item).strip()
        for item in _as_clean_list(meta.get("model_fallback_reason") or event.get("model_fallback_reason"))
        if str(item).strip()
    ]
    return {
        "model_id": meta.get("model_id") or event.get("model_id"),
        "model_display_name": meta.get("model_display_name") or event.get("model_display_name"),
        "backend": meta.get("model_backend") or meta.get("backend") or event.get("model_backend"),
        "resolved_model_path": meta.get("resolved_model_path") or event.get("resolved_model_path"),
        "model_fallback_reason": fallback_reason,
    }


def _resolve_confirm_choice_confidence(choice: str, previous_case_event: dict[str, Any]) -> float | None:
    normalized_choice = str(choice or "").strip()
    if not normalized_choice:
        return None

    for candidates in (
        _normalize_top3_candidates(previous_case_event.get("fusion_top3")),
        _normalize_top3_candidates(_safe_record(previous_case_event.get("image_result")).get("top3")),
        _normalize_top3_candidates(previous_case_event.get("text_top3")),
    ):
        for disease, prob in candidates:
            if disease == normalized_choice:
                return float(prob)

    diagnosis_evidence = _safe_record(previous_case_event.get("diagnosis_evidence"))
    fallback_zero: float | None = None
    for raw in (
        previous_case_event.get("final_confidence"),
        diagnosis_evidence.get("final_confidence"),
        _safe_record(previous_case_event.get("image_result")).get("confidence"),
        previous_case_event.get("image_confidence"),
        previous_case_event.get("text_confidence"),
    ):
        value = _safe_float(raw)
        if value is None:
            continue
        if value > 0:
            return value
        fallback_zero = value
    return fallback_zero


def _inherit_previous_diagnosis_context(
    state: dict[str, Any],
    *,
    choice: str,
    previous_case_event: dict[str, Any],
) -> dict[str, Any]:
    previous_image_result = _safe_record(previous_case_event.get("image_result"))
    image_diagnosis = _build_image_diagnosis_from_event(previous_case_event)
    model_meta = _extract_event_model_meta(previous_case_event)
    text_top3 = _normalize_top3_candidates(previous_case_event.get("text_top3"))
    fusion_top3 = _normalize_top3_candidates(previous_case_event.get("fusion_top3"))
    diagnosis_evidence = previous_case_event.get("diagnosis_evidence")
    resolved_confidence = _resolve_confirm_choice_confidence(choice, previous_case_event)
    image_confidence = _safe_float(previous_case_event.get("image_confidence"))
    if image_confidence is None:
        image_confidence = _safe_float(previous_image_result.get("confidence"))
    text_confidence = _safe_float(previous_case_event.get("text_confidence"))

    state["final_disease"] = choice
    state["disease_type"] = choice
    state["final_source"] = "user_confirmed_candidate"
    state["final_confidence"] = resolved_confidence
    state["disease_confidence"] = resolved_confidence
    state["image_confidence"] = image_confidence
    state["text_confidence"] = text_confidence
    state["text_top3"] = text_top3
    state["fusion_top3"] = fusion_top3
    state["diagnosis_evidence"] = diagnosis_evidence if isinstance(diagnosis_evidence, dict) else None
    state["modality_conflict_flag"] = previous_case_event.get("modality_conflict_flag")
    state["image_reliable"] = previous_case_event.get("image_reliable")
    state["text_reliable"] = previous_case_event.get("text_reliable")
    state["reliability_issue_types"] = list(previous_case_event.get("reliability_issue_types") or [])
    state["supplement_mode"] = str(previous_case_event.get("supplement_mode") or "none")
    state["image_diagnosis"] = image_diagnosis
    state["image_result"] = previous_image_result
    state["diagnosis_model_meta"] = model_meta
    if not state.get("diagnosis_model_id") and model_meta.get("model_id"):
        state["diagnosis_model_id"] = model_meta.get("model_id")

    return {
        "final_confidence": resolved_confidence,
        "final_source": state.get("final_source"),
        "image_confidence": image_confidence,
        "text_confidence": text_confidence,
        "model_display_name": model_meta.get("model_display_name"),
        "fusion_top3": fusion_top3,
        "image_top3": image_diagnosis.get("top3") or [],
    }


def _normalize_expert_review_decision(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"accept", "decline"}:
        return normalized
    raise HTTPException(status_code=400, detail="expert_review_decision 必须为 accept / decline / null")


def _ensure_follow_up_plan(state: dict[str, Any]) -> dict[str, Any]:
    if not state.get("kb_snapshot"):
        state = kb_retrieval_agent(state)
    if not (str(state.get("treatment_plan") or "").strip() and str(state.get("prevention_advice") or "").strip()):
        state = treatment_agent(state)
    if state.get("verification_result") is None:
        state = verification_agent(state)
    return state


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
    request: Request,
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
    actor = _get_request_actor(request)
    farmer_id = _apply_farmer_scope(actor, farmer_id)
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
    runtime_thresholds = get_runtime_thresholds()
    if top1_conf < float(runtime_thresholds["diagnosis_conf_threshold"]):
        fallback_reasons.append("low_confidence")
    if top2_conf is not None and (top1_conf - top2_conf) < float(runtime_thresholds["low_margin_threshold"]):
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
    image_refs = _build_image_refs(unique_name)
    image_url = image_refs["image_url"]

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
    image_reliable: bool | None = None
    text_reliable: bool | None = None
    reliability_issue_types: list[str] = []
    supplement_mode: str = "none"
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

    response_status = "waiting_for_supplement" if need_confirm_waiting else "completed"
    expert_review_recommended = False
    expert_review_selected = False
    expert_review_status = "NONE"
    verification_available = verification_result is not None
    treatment_available = treatment is not None
    response_fallback_reason = (trace_fallback_reason or fallback_reasons or None) if fallback_used else None
    confirm_reasons = dedupe_reasons(trace_fallback_reason or [])
    fusion_mode = _derive_fusion_mode(final_source, (final_state or {}).get("diagnosis_evidence"))
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
        **image_refs,
        "image_result": image_result_dict,
        "fallback_used": fallback_used,
        "fallback_reason": response_fallback_reason,
        "confirm_reasons": confirm_reasons,
        "rule_result": rule_result_dict,
        "final_disease": final_state.get("final_disease") if final_state else final_disease,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "fusion_mode": fusion_mode,
        "confirm_round": False,
        "source_stage": "initial",
        "selected_branch": flags.get("selected_branch"),
        "personalization_applied": personalization_applied,
        "personalization_reasons": dedupe_reasons(flags.get("personalization_reasons") or []),
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
        "image_reliable": (final_state or {}).get("image_reliable"),
        "text_reliable": (final_state or {}).get("text_reliable"),
        "reliability_issue_types": list((final_state or {}).get("reliability_issue_types") or []),
        "supplement_mode": str((final_state or {}).get("supplement_mode") or "none"),
        "status": response_status,
        "treatment_skipped_due_need_confirm": need_confirm_waiting,
        "treatment_available": treatment_available,
        "verification_available": verification_available,
        "manual_review_recommended": False,
        "manual_review_required_before_execution": False,
        "expert_review_recommended": expert_review_recommended,
        "expert_review_selected": expert_review_selected,
        "expert_review_status": expert_review_status,
        "assigned_expert_id": None,
        "expert_review_result": None,
        "expert_review_supplement_symptoms": None,
        "expert_review_notes": None,
        "expert_reviewed_at": None,
        "expert_review_actions": [],
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

    if response_status == "waiting_for_supplement":
        emit_node_event(
            trace_id,
            node="AwaitUserConfirmation",
            status="end",
            message="当前轮返回追问，等待用户进入补充诊断",
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
        **image_refs,
        "image_result": image_result_dict,
        "fallback_used": fallback_used,
        "fallback_reason": response_fallback_reason,
        "confirm_reasons": confirm_reasons,
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
        "llm_failed_reason": flags.get("llm_failed_reason"),
        "trace_id": trace_id,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "fusion_mode": fusion_mode,
        "model_id": model_meta.get("model_id"),
        "model_display_name": model_meta.get("model_display_name"),
        "model_backend": model_meta.get("backend"),
        "resolved_model_path": model_meta.get("resolved_model_path"),
        "model_fallback_reason": model_meta.get("model_fallback_reason"),
        "text_top3": list((final_state or {}).get("text_top3") or []),
        "fusion_top3": list((final_state or {}).get("fusion_top3") or []),
        "diagnosis_evidence": (final_state or {}).get("diagnosis_evidence"),
        "modality_conflict_flag": (final_state or {}).get("modality_conflict_flag"),
        "image_reliable": (final_state or {}).get("image_reliable"),
        "text_reliable": (final_state or {}).get("text_reliable"),
        "reliability_issue_types": list((final_state or {}).get("reliability_issue_types") or []),
        "supplement_mode": str((final_state or {}).get("supplement_mode") or "none"),
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
        "expert_review_recommended": expert_review_recommended,
        "expert_review_selected": expert_review_selected,
        "expert_review_status": expert_review_status,
        "assigned_expert_id": None,
        "expert_review_result": None,
        "expert_review_supplement_symptoms": None,
        "expert_review_notes": None,
        "expert_reviewed_at": None,
        "expert_review_actions": [],
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
def diagnose_confirm(request: Request, payload: dict = Body(...)) -> dict:
    request_started = time.perf_counter()
    trace_id = payload.get("trace_id")
    previous_trace_id = payload.get("previous_trace_id")
    image_id = payload.get("image_id")
    crop_type = payload.get("crop_type") or "番茄"
    symptoms = payload.get("symptoms") or []
    growth_stage = payload.get("growth_stage")
    model_id = payload.get("model_id")
    choice = str(payload.get("choice") or "").strip()
    expert_review_decision = _normalize_expert_review_decision(payload.get("expert_review_decision"))
    farmer_id = payload.get("farmer_id")
    base_id = payload.get("base_id")

    actor = _get_request_actor(request)
    farmer_id = _apply_farmer_scope(actor, str(farmer_id) if farmer_id is not None else None)

    if not image_id:
        raise HTTPException(status_code=400, detail="image_id 不能为空")

    # 保持补充诊断沿用首轮 trace，便于流程面板展示完整链路
    if not trace_id and previous_trace_id:
        trace_id = previous_trace_id
    if not trace_id:
        trace_id = uuid.uuid4().hex

    if not isinstance(symptoms, list):
        raise HTTPException(status_code=400, detail="symptoms 必须为列表")

    # 确认输入是同一张图内的“等待用户补充 -> 回边重试”状态折返。
    # 因此确认输入症状必须与上一轮症状做增量合并，避免覆盖。
    history_events = list_trace_events(trace_id)
    previous_case_event = _latest_case_event_by_trace(trace_id)
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

    image_path = (UPLOAD_DIR / image_id).resolve()
    if not image_path.exists():
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
    state["historical_symptoms"] = historical_symptoms
    state["confirm_round_index"] = confirm_round_index
    state["user_choice"] = choice or None
    state["current_step"] = "confirm_input"

    append_trace(
        state,
        agent="confirm_input",
        inputs={
            "symptoms": state["symptoms"],
            "historical_symptoms": historical_symptoms,
            "incoming_symptoms": incoming_symptoms,
            "crop_type": crop_type,
            "growth_stage": normalize_growth_stage_code(growth_stage),
            "image_id": image_id,
            "previous_trace_id": previous_trace_id or trace_id,
            "confirm_round_parent_trace_id": trace_id,
            "model_id": model_id,
            "choice": choice,
            "farmer_id": farmer_id,
            "base_id": base_id,
            "confirm_round_index": confirm_round_index,
        },
        outputs={},
    )
    if choice and choice != "other":
        inherited_context = _inherit_previous_diagnosis_context(
            state,
            choice=choice,
            previous_case_event=previous_case_event,
        )
        flags = state.get("personalization_flags") or {}
        flags["need_confirm"] = False
        state["personalization_flags"] = flags
        append_trace(
            state,
            agent="confirm_choice",
            inputs={"choice": choice},
            outputs={
                "final_disease": choice,
                "need_confirm": False,
                "final_source": state.get("final_source"),
                "final_confidence": state.get("final_confidence"),
                "inherited_context": inherited_context,
            },
        )

    # 低置信度回退分支：由 supervisor 做统一路由决策，避免形成平行独立流程。
    terminal_action: str | None = None
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
        elif next_action == "await_user_confirmation":
            terminal_action = "await_user_confirmation"
            break
        elif next_action == "manual_review":
            terminal_action = "manual_review"
            break
        elif next_action == "end":
            terminal_action = "end"
            break
        else:
            terminal_action = next_action or "end"
            break

    final_confidence = state.get("final_confidence")
    final_source = state.get("final_source")
    image_confidence = state.get("image_confidence")
    text_confidence = state.get("text_confidence")
    text_top3 = list(state.get("text_top3") or [])
    fusion_top3 = list(state.get("fusion_top3") or [])
    modality_conflict_flag = state.get("modality_conflict_flag")
    diagnosis_evidence = state.get("diagnosis_evidence")
    image_reliable = state.get("image_reliable")
    text_reliable = state.get("text_reliable")
    reliability_issue_types = list(state.get("reliability_issue_types") or [])
    supplement_mode = str(state.get("supplement_mode") or "none")

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
    expert_review_recommended = False
    expert_review_selected = False
    expert_review_status = "NONE"
    expert_review_actions: list[str] = []
    if terminal_action == "await_user_confirmation":
        manual_review_recommended = False
        need_confirm = True
        confirm_status = "waiting_for_supplement"
    elif terminal_action == "manual_review":
        expert_review_recommended = True
        manual_review_recommended = True
        expert_review_actions = ["use_current_result", "request_expert_review"]
        need_confirm = False
        if expert_review_decision == "decline":
            state = _ensure_follow_up_plan(state)
            final_confidence = state.get("final_confidence")
            final_source = state.get("final_source")
            image_confidence = state.get("image_confidence")
            text_confidence = state.get("text_confidence")
            text_top3 = list(state.get("text_top3") or [])
            fusion_top3 = list(state.get("fusion_top3") or [])
            modality_conflict_flag = state.get("modality_conflict_flag")
            diagnosis_evidence = state.get("diagnosis_evidence")
            image_reliable = state.get("image_reliable")
            text_reliable = state.get("text_reliable")
            reliability_issue_types = list(state.get("reliability_issue_types") or [])
            supplement_mode = str(state.get("supplement_mode") or "none")
            image_diagnosis = state.get("image_diagnosis") or {}
            image_top1 = image_diagnosis.get("top1") or {}
            top3 = image_diagnosis.get("top3") or []
            expert_review_selected = False
            expert_review_status = "DECLINED"
            confirm_status = "completed"
            manual_review_required_before_execution = False
        elif expert_review_decision == "accept":
            expert_review_selected = True
            expert_review_status = "PENDING"
            confirm_status = "pending_expert_review"
            manual_review_required_before_execution = True
        else:
            expert_review_selected = False
            expert_review_status = "NONE"
            confirm_status = "waiting_for_expert_decision"
            manual_review_required_before_execution = False
    else:
        if choice and choice != "other":
            need_confirm = False
        manual_review_recommended = False
        confirm_status = "completed"
        manual_review_required_before_execution = False
    flags = state.get("personalization_flags") or flags
    if confirm_status == "pending_expert_review":
        state["treatment_plan"] = None
        state["prevention_advice"] = None
        state["verification_result"] = None
        state["verification_passed"] = None
        state["verification_risk_level"] = None
        state["verification_issues"] = []
        state["verification_summary"] = None
    elif confirm_status in {"waiting_for_supplement", "waiting_for_expert_decision"} and terminal_action == "manual_review":
        state["treatment_plan"] = None
        state["prevention_advice"] = None
        state["verification_result"] = None
        state["verification_passed"] = None
        state["verification_risk_level"] = None
        state["verification_issues"] = []
        state["verification_summary"] = None

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
    if confirm_status == "pending_expert_review":
        confirm_message = "已进入待专家复核状态，后续将由专家确认病害并补充最终方案。"
    elif confirm_status == "waiting_for_expert_decision" and expert_review_recommended:
        confirm_message = "多次补充后仍存在不确定性。你可以使用当前结果结束，或转入待专家复核状态。"
    elif confirm_status == "waiting_for_supplement":
        confirm_message = "置信度较低，建议补充症状、确认候选病害或重新拍摄。"

    carried_fallback_used = bool(previous_case_event.get("fallback_used")) if isinstance(previous_case_event, dict) else False
    carried_fallback_reason = previous_case_event.get("fallback_reason") if isinstance(previous_case_event, dict) else None
    carried_rule_result = previous_case_event.get("rule_result") if isinstance(previous_case_event, dict) else None
    confirm_reasons = dedupe_reasons(flags.get("fallback_reason") or [])
    fusion_mode = _derive_fusion_mode(final_source, diagnosis_evidence)
    carried_personalization_reasons = dedupe_reasons(
        (flags.get("personalization_reasons") or (previous_case_event.get("personalization_reasons") if isinstance(previous_case_event, dict) else []) or [])
    )

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
        **_build_image_refs(image_id),
        "image_result": image_result,
        "fallback_used": carried_fallback_used,
        "fallback_reason": carried_fallback_reason,
        "confirm_reasons": confirm_reasons,
        "rule_result": carried_rule_result,
        "final_disease": state.get("final_disease"),
        "need_confirm": need_confirm,
        "final_confidence": final_confidence if final_confidence is not None else image_result.get("confidence"),
        "final_source": final_source or "confirm",
        "fusion_mode": fusion_mode,
        "confirm_round": True,
        "confirm_round_parent_trace_id": trace_id,
        "source_stage": "confirm",
        "selected_branch": flags.get("selected_branch"),
        "personalization_applied": personalization_applied,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "llm_failed": bool(flags.get("llm_failed")),
        "elapsed_ms": round((time.perf_counter() - request_started) * 1000, 2),
        "treatment": None if confirm_status == "pending_expert_review" else {
            "plan": state.get("treatment_plan"),
            "prevention": state.get("prevention_advice"),
        },
        "meta": response_meta,
        "verification_result": None if confirm_status == "pending_expert_review" else state.get("verification_result"),
        "verification_passed": None if confirm_status == "pending_expert_review" else state.get("verification_passed"),
        "verification_risk_level": None if confirm_status == "pending_expert_review" else state.get("verification_risk_level"),
        "verification_issues": [] if confirm_status == "pending_expert_review" else list(state.get("verification_issues") or []),
        "verification_summary": None if confirm_status == "pending_expert_review" else state.get("verification_summary"),
        "image_confidence": image_confidence,
        "text_confidence": text_confidence,
        "text_top3": text_top3,
        "fusion_top3": fusion_top3,
        "modality_conflict_flag": modality_conflict_flag,
        "diagnosis_evidence": diagnosis_evidence,
        "image_reliable": image_reliable,
        "text_reliable": text_reliable,
        "reliability_issue_types": reliability_issue_types,
        "supplement_mode": supplement_mode,
        "manual_review_recommended": manual_review_recommended,
        "manual_review_required_before_execution": manual_review_required_before_execution,
        "expert_review_recommended": expert_review_recommended,
        "expert_review_selected": expert_review_selected,
        "expert_review_status": expert_review_status,
        "assigned_expert_id": previous_case_event.get("assigned_expert_id") if isinstance(previous_case_event, dict) else None,
        "expert_review_result": previous_case_event.get("expert_review_result") if isinstance(previous_case_event, dict) else None,
        "expert_review_supplement_symptoms": previous_case_event.get("expert_review_supplement_symptoms") if isinstance(previous_case_event, dict) else None,
        "expert_review_notes": previous_case_event.get("expert_review_notes") if isinstance(previous_case_event, dict) else None,
        "expert_reviewed_at": previous_case_event.get("expert_reviewed_at") if isinstance(previous_case_event, dict) else None,
        "expert_review_actions": expert_review_actions,
        "status": confirm_status,
        "treatment_available": bool(state.get("treatment_plan")) and confirm_status != "pending_expert_review",
        "verification_available": (state.get("verification_result") is not None) and confirm_status != "pending_expert_review",
        "graph_treatment_generated": bool(state.get("treatment_plan")),
        "fallback_treatment_used": bool(previous_case_event.get("fallback_treatment_used")) if isinstance(previous_case_event, dict) else False,
        "historical_follow_up_questions": historical_follow_up_questions,
    }
    event = serialize_final_response(event)
    emit_node_event(trace_id, node="Persist", status="start", message="写入确认轮事件日志")
    try:
        append_event(serialize_final_response(event))
        emit_node_event(trace_id, node="Persist", status="end", message="确认轮事件落盘完成")
    except Exception as exc:
        print(f"Warning: failed to append confirm event: {exc}")
        emit_node_event(trace_id, node="Persist", status="error", message=f"确认轮事件落盘失败: {exc}")

    # Final 必须在 Persist 之后，才是真正终点
    if confirm_status == "waiting_for_supplement":
        emit_node_event(
            trace_id,
            node="AwaitUserConfirmation",
            status="end",
            message="当前轮返回追问，等待用户进入补充诊断",
            payload={
                "final_disease": state.get("final_disease"),
                "status": confirm_status,
                "reason": "need_confirm_wait_user",
            },
        )
    else:
        emit_final_event_once(
            trace_id,
            status=confirm_status,
            message="补充诊断流程完成",
            payload={
                "final_disease": state.get("final_disease"),
                "confirm_round": True,
                "status": confirm_status,
            },
        )

    events = list_trace_events(trace_id)

    response_payload = {
        "trace_id": trace_id,
        **_build_image_refs(image_id),
        "fallback_used": carried_fallback_used,
        "fallback_reason": carried_fallback_reason,
        "confirm_reasons": confirm_reasons,
        "rule_result": carried_rule_result,
        "final_disease": state.get("final_disease"),
        "image_result": image_result,
        "farmer_id": farmer_id,
        "need_confirm": need_confirm,
        "final_confidence": final_confidence,
        "final_source": final_source,
        "fusion_mode": fusion_mode,
        "image_confidence": image_confidence,
        "text_confidence": text_confidence,
        "text_top3": text_top3,
        "fusion_top3": fusion_top3,
        "normalized_symptoms": list(
            state.get("normalized_symptoms")
            or ((state.get("structured_symptoms") or {}).get("normalized_symptoms") or [])
            or []
        ),
        "modality_conflict_flag": modality_conflict_flag,
        "diagnosis_evidence": diagnosis_evidence,
        "image_reliable": image_reliable,
        "text_reliable": text_reliable,
        "reliability_issue_types": reliability_issue_types,
        "supplement_mode": supplement_mode,
        "manual_review_recommended": manual_review_recommended,
        "manual_review_required_before_execution": manual_review_required_before_execution,
        "expert_review_recommended": expert_review_recommended,
        "expert_review_selected": expert_review_selected,
        "expert_review_status": expert_review_status,
        "assigned_expert_id": previous_case_event.get("assigned_expert_id") if isinstance(previous_case_event, dict) else None,
        "expert_review_result": previous_case_event.get("expert_review_result") if isinstance(previous_case_event, dict) else None,
        "expert_review_supplement_symptoms": previous_case_event.get("expert_review_supplement_symptoms") if isinstance(previous_case_event, dict) else None,
        "expert_review_notes": previous_case_event.get("expert_review_notes") if isinstance(previous_case_event, dict) else None,
        "expert_reviewed_at": previous_case_event.get("expert_reviewed_at") if isinstance(previous_case_event, dict) else None,
        "expert_review_actions": expert_review_actions,
        "status": confirm_status,
        "confirm_message": confirm_message,
        "treatment": None if confirm_status == "pending_expert_review" else {
            "plan": state.get("treatment_plan"),
            "prevention": state.get("prevention_advice"),
        },
        "model_id": model_meta.get("model_id"),
        "model_display_name": model_meta.get("model_display_name"),
        "model_backend": model_meta.get("backend"),
        "resolved_model_path": model_meta.get("resolved_model_path"),
        "model_fallback_reason": model_meta.get("model_fallback_reason"),
        "profile_farm_scale": flags.get("farm_scale"),
        "profile_pesticide_access_level": flags.get("pesticide_access_level"),
        "profile_equipment": [str(item) for item in (flags.get("equipment") or [])],
        "profile_cultivation_mode": flags.get("cultivation_mode"),
        "selected_branch": flags.get("selected_branch") if (bool(state.get("treatment_plan")) and confirm_status != "pending_expert_review") else None,
        "workflow_degraded": bool(previous_case_event.get("workflow_degraded")) if isinstance(previous_case_event, dict) else False,
        "degraded_reason": previous_case_event.get("degraded_reason") if isinstance(previous_case_event, dict) else None,
        "personalization_applied": personalization_applied,
        "personalization_reasons": carried_personalization_reasons,
        "filtered": filtered,
        "filtered_reasons": filtered_reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
        "follow_up_questions": follow_up_questions,
        "historical_follow_up_questions": historical_follow_up_questions,
        "missing_profile_fields": missing_profile_fields,
        "llm_failed": bool(flags.get("llm_failed")),
        "llm_failed_reason": flags.get("llm_failed_reason"),
        "verification_result": None if confirm_status == "pending_expert_review" else state.get("verification_result"),
        "verification_passed": None if confirm_status == "pending_expert_review" else state.get("verification_passed"),
        "verification_risk_level": None if confirm_status == "pending_expert_review" else state.get("verification_risk_level"),
        "verification_issues": [] if confirm_status == "pending_expert_review" else list(state.get("verification_issues") or []),
        "verification_summary": None if confirm_status == "pending_expert_review" else state.get("verification_summary"),
        "treatment_available": bool(state.get("treatment_plan")) and confirm_status != "pending_expert_review",
        "verification_available": (state.get("verification_result") is not None) and confirm_status != "pending_expert_review",
        "graph_treatment_generated": bool(state.get("treatment_plan")),
        "fallback_treatment_used": bool(previous_case_event.get("fallback_treatment_used")) if isinstance(previous_case_event, dict) else False,
        "treatment_skipped_due_need_confirm": bool(confirm_status in {"waiting_for_supplement", "waiting_for_expert_decision"}),
        "confirm_round_parent_trace_id": trace_id,
        "meta": response_meta,
        "events": events,
    }
    response_payload["previous_trace_id"] = previous_trace_id or trace_id
    return serialize_final_response(response_payload)


@app.get("/api/models")
def get_models() -> dict[str, object]:
    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    return {"models": list_models(allow_torch=allow_torch)}


@app.get("/api/profiles")
def list_profiles(request: Request) -> dict[str, list[dict[str, str | None]]]:
    actor = _get_request_actor(request)
    requested_farmer_id = _resolve_default_profile_id(actor, None)
    scoped_farmer_id = _apply_farmer_scope(actor, requested_farmer_id)
    profiles = []
    for farmer_id in list_profile_ids_mysql():
        if scoped_farmer_id and farmer_id != scoped_farmer_id:
            continue
        profile = get_profile_mysql(farmer_id) or {}
        owner_user_id = str(profile.get("owner_user_id") or "").strip()
        profiles.append({
            "id": farmer_id,
            "farmer_id": farmer_id,
            "name": profile.get("name"),
            "display_name": profile.get("display_name"),
            "owner_user_id": owner_user_id or None,
            "path": str(get_profile_path(farmer_id)),
        })
    return {"profiles": profiles}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _clone_case_event_for_append(event: dict[str, Any]) -> dict[str, Any]:
    next_event = dict(event)
    new_id = uuid.uuid4().hex
    next_event["id"] = new_id
    # event_store/mysql ORM 优先使用 event_id 作为唯一业务事件键，必须同时刷新。
    next_event["event_id"] = new_id
    next_event["ts"] = _utc_now_iso()
    return next_event


def _build_image_refs(image_id: str | None) -> dict[str, str]:
    normalized = str(image_id or "").strip()
    if not normalized:
        return {"image_id": "", "image_url": ""}
    return {"image_id": normalized, "image_url": f"/uploads/{normalized}"}




def _collect_existing_base_ids(exclude_farmer_id: str | None = None) -> dict[str, str]:
    """收集系统内已有基地ID -> 所属farmer_id（用于全局唯一校验）。"""
    result: dict[str, str] = {}
    for existing_farmer_id in list_profile_ids_mysql():
        if exclude_farmer_id and existing_farmer_id == exclude_farmer_id:
            continue
        profile = get_profile_mysql(existing_farmer_id)
        if not profile or not isinstance(profile, dict):
            continue
        bases = profile.get("bases")
        if not isinstance(bases, dict):
            continue
        for base_id in bases.keys():
            result[base_id] = existing_farmer_id
    return result


@app.get("/api/profiles/base-ids")
def list_all_base_ids(request: Request) -> dict[str, list[dict[str, str]]]:
    actor = _get_request_actor(request)
    scoped_farmer_id = _apply_farmer_scope(actor, None)
    items = []
    for base_id, owner in sorted(_collect_existing_base_ids().items(), key=lambda item: (item[0], item[1])):
        if scoped_farmer_id and owner != scoped_farmer_id:
            continue
        items.append({"base_id": base_id, "farmer_id": owner})
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
    existing_ids = []
    for farmer_id in list_profile_ids():
        try:
            if farmer_id.startswith("F") and farmer_id[1:].isdigit():
                existing_ids.append(int(farmer_id[1:]))
        except Exception:
            pass

    if not existing_ids:
        return "F0001"

    # 生成下一个ID
    next_id = max(existing_ids) + 1
    return f"F{next_id:04d}"


@app.post("/api/profiles")
def create_profile(request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    _ = request
    _ = payload
    raise HTTPException(status_code=400, detail="档案创建入口已废弃，请通过账号管理创建账号")


@app.get("/api/profiles/{farmer_id}")
def get_profile(farmer_id: str, request: Request) -> dict:
    actor = _get_request_actor(request)
    scoped_farmer_id = _apply_farmer_scope(actor, farmer_id)
    if scoped_farmer_id and scoped_farmer_id != farmer_id:
        raise HTTPException(status_code=403, detail="当前角色仅允许访问自己的档案")
    profile = get_profile_mysql(farmer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="档案不存在")
    return profile


@app.post("/api/profiles/{farmer_id}")
def save_profile_route(farmer_id: str, request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    actor = _get_request_actor(request)
    scoped_farmer_id = _apply_farmer_scope(actor, farmer_id)
    if scoped_farmer_id and scoped_farmer_id != farmer_id:
        raise HTTPException(status_code=403, detail="当前角色仅允许修改自己的档案")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="档案内容非法")
    actor_user_id = str(actor.get("user_id") or "").strip()
    if not _is_admin(actor):
        payload = dict(payload)
        payload["owner_user_id"] = actor_user_id or farmer_id
        payload["display_name"] = payload.get("display_name") or payload.get("name") or farmer_id
    owner_user_id = str(payload.get("owner_user_id") or "").strip() or farmer_id
    if owner_user_id != farmer_id:
        raise HTTPException(status_code=400, detail="一账号一档案阶段 owner_user_id 必须与 farmer_id 相同")
    if not _is_admin(actor) and actor_user_id and owner_user_id != actor_user_id:
        raise HTTPException(status_code=403, detail="当前角色仅允许修改自己的档案")
    with get_db_session() as session:
        _validate_account_exists(session, owner_user_id)
    payload = dict(payload)
    try:
        profile = _normalize_profile_payload_for_save(farmer_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"档案格式非法: {exc}") from exc
    try:
        save_profile_payload_mysql(profile.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存档案失败: {exc}") from exc
    return {"ok": True, "farmer_id": farmer_id}


@app.delete("/api/profiles/{farmer_id}")
def delete_profile(farmer_id: str, request: Request) -> dict[str, bool]:
    _ = farmer_id
    _ = request
    raise HTTPException(status_code=400, detail="档案删除入口已废弃，请通过账号管理删除账号")


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


def _refresh_base_weather(profile: FarmerProfile, base_id: str) -> dict[str, Any]:
    base = profile.bases.get(base_id)
    if base is None:
        raise HTTPException(status_code=404, detail="基地不存在")
    if base.latitude is None or base.longitude is None:
        raise HTTPException(status_code=400, detail="基地缺少经纬度，无法刷新天气")

    weather = weather_summary(lat=float(base.latitude), lon=float(base.longitude))
    refreshed_at = _utc_now_iso()
    summary = str(weather.get("summary") or "").strip()
    if summary:
        base.weather_snapshot = summary
        base.environment = summary
    base.relative_humidity_2m = weather.get("relative_humidity_2m")
    base.precipitation = weather.get("precipitation")
    base.rain_risk = weather.get("rain_risk")
    base.weather_temperature_2m = weather.get("temperature_2m")
    base.weather_wind_speed_10m = weather.get("wind_speed_10m")
    base.last_weather_refresh_at = refreshed_at
    profile.bases[base_id] = base
    profile.updated_at = refreshed_at
    return {
        "base_id": base_id,
        "weather_snapshot": base.weather_snapshot,
        "relative_humidity_2m": base.relative_humidity_2m,
        "precipitation": base.precipitation,
        "rain_risk": base.rain_risk,
        "temperature_2m": weather.get("temperature_2m"),
        "wind_speed_10m": weather.get("wind_speed_10m"),
        "weather_desc": weather.get("weather_desc"),
        "last_weather_refresh_at": refreshed_at,
    }


def _should_write_weather_snapshot() -> bool:
    mode = str(PROFILE_STORE_MODE or "file").strip().lower()
    return mode in {"mysql", "dual"}


def _upsert_weather_snapshot_from_refresh(
    *,
    farmer_id: str,
    profile: FarmerProfile,
    base_id: str,
    payload: dict[str, Any],
) -> None:
    base = profile.bases.get(base_id)
    if base is None:
        return
    snapshot_payload = {
        "farmer_id": farmer_id,
        "base_id": base_id,
        "lat": base.latitude,
        "lon": base.longitude,
        "temperature": payload.get("temperature_2m"),
        "humidity": payload.get("relative_humidity_2m"),
        "precipitation": payload.get("precipitation"),
        "rain_probability": payload.get("rain_risk"),
        "weather_code": None,
        "weather_desc": payload.get("weather_desc"),
        "source": "open-meteo",
        "snapshot_time": payload.get("last_weather_refresh_at"),
        "raw_json": dict(payload),
    }
    upsert_weather_snapshot_mysql(snapshot_payload)


@app.post("/api/profiles/{farmer_id}/bases/{base_id}/weather/refresh")
def refresh_base_weather(farmer_id: str, base_id: str, request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    scoped_farmer_id = _apply_farmer_scope(actor, farmer_id)
    if scoped_farmer_id and scoped_farmer_id != farmer_id:
        raise HTTPException(status_code=403, detail="当前角色仅允许操作自己的档案")
    profile_payload = get_profile_mysql(farmer_id)
    if profile_payload is None:
        raise HTTPException(status_code=404, detail="档案不存在")
    try:
        profile = FarmerProfile.model_validate(profile_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"档案格式非法，无法刷新天气: {exc}") from exc

    payload = _refresh_base_weather(profile, base_id)
    if _should_write_weather_snapshot():
        try:
            _upsert_weather_snapshot_from_refresh(
                farmer_id=farmer_id,
                profile=profile,
                base_id=base_id,
                payload=payload,
            )
        except Exception as exc:
            print(f"[WeatherSnapshot] upsert weather_snapshots 失败（已忽略，不影响主流程）: {exc}")
    try:
        save_profile_payload_mysql(profile.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"天气刷新后保存档案失败: {exc}") from exc
    return {"ok": True, **payload}


@app.get("/api/weather/snapshots")
def list_weather_snapshots(
    request: Request,
    farmer_id: str | None = None,
    base_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    scoped_farmer_id = _scoped_farmer_query(request, farmer_id)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    safe_limit = max(1, min(1000, int(limit)))
    if not _should_write_weather_snapshot():
        return {"items": []}
    items = list_weather_snapshots_mysql(
        farmer_id=scoped_farmer_id,
        base_id=base_id,
        start=start,
        end=end,
        limit=safe_limit,
    )
    return {"items": items}



@app.get("/api/events")
def get_events(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    farmer_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    actor = _get_request_actor(request)
    scoped_farmer_id = _apply_farmer_scope(actor, farmer_id)
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        events = list_events_range(start, end, limit)
        filtered_events = [
            event for event in events
            if not scoped_farmer_id or _event_farmer_id(event) == scoped_farmer_id
        ]
        return {"events": [_serialize_event_dto(event, inject_trace_steps=True) for event in filtered_events]}
    events = list_events(limit)
    filtered_events = [
        event for event in events
        if not scoped_farmer_id or _event_farmer_id(event) == scoped_farmer_id
    ]
    return {"events": [_serialize_event_dto(event, inject_trace_steps=True) for event in filtered_events]}


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    user_id = str(payload.user_id or "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    with get_db_session() as session:
        account = session.execute(
            select(UserAccountORM).where(UserAccountORM.user_id == user_id)
        ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=401, detail="账号不存在")
    if str(account.status or "").upper() != "ACTIVE":
        raise HTTPException(status_code=403, detail="账号已禁用")
    incoming_password = str(payload.password or "").strip()
    stored_password = str(account.password or "").strip()
    if stored_password and stored_password != incoming_password:
        raise HTTPException(status_code=401, detail="密码错误")
    return {
        "user_id": account.user_id,
        "display_name": account.display_name,
        "role": str(account.role or "USER").upper(),
        "linked_farmer_id": account.linked_farmer_id,
        "status": account.status,
    }


@app.get("/api/admin/accounts")
def list_admin_accounts(request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    with get_db_session() as session:
        rows = session.execute(
            select(UserAccountORM).order_by(UserAccountORM.user_id.asc())
        ).scalars().all()
        owner_map = {
            str(item.owner_user_id or "").strip(): str(item.farmer_id or "").strip()
            for item in session.execute(select(FarmerProfileORM)).scalars().all()
            if str(item.owner_user_id or "").strip()
        }
    items = []
    for row in rows:
        user_id = str(row.user_id or "").strip()
        items.append(
            {
                "user_id": user_id,
                "username": row.username,
                "display_name": row.display_name,
                "role": str(row.role or "USER").strip().upper(),
                "status": str(row.status or "ACTIVE").strip().upper(),
                "farmer_id": user_id,
                "owner_user_id": user_id,
                "profile_farmer_id": owner_map.get(user_id) or user_id,
            }
        )
    return {"items": items}


@app.post("/api/admin/accounts")
def create_admin_account(request: Request, payload: AdminCreateAccountRequest) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    try:
        with get_db_session() as session:
            account, profile = _create_account_with_profile(
                session,
                username=payload.username,
                display_name=payload.display_name,
                password=payload.password,
                role=payload.role,
            )
            session.commit()
            return {
                "ok": True,
                "user_id": account.user_id,
                "farmer_id": profile.farmer_id,
                "role": str(account.role or "USER").strip().upper(),
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"新增账号失败: {exc}") from exc


@app.post("/api/admin/accounts/{user_id}/role")
def update_admin_account_role(user_id: str, request: Request, payload: AdminUpdateAccountRoleRequest) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    normalized_role = str(payload.role or "").strip().upper()
    if normalized_role not in SUPPORTED_ROLES:
        raise HTTPException(status_code=400, detail="非法角色类型")
    with get_db_session() as session:
        account = _validate_account_exists(session, normalized_user_id)
        account.role = normalized_role
        session.commit()
    return {"ok": True, "user_id": normalized_user_id, "role": normalized_role}


@app.delete("/api/admin/accounts/{user_id}")
def delete_admin_account(user_id: str, request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    if normalized_user_id == str(actor.get("user_id") or "").strip():
        raise HTTPException(status_code=400, detail="不允许删除当前登录管理员账号")
    with get_db_session() as session:
        account = session.execute(
            select(UserAccountORM).where(UserAccountORM.user_id == normalized_user_id)
        ).scalar_one_or_none()
        if account is None:
            raise HTTPException(status_code=404, detail="账号不存在")
        profile_rows = session.execute(
            select(FarmerProfileORM).where(
                (FarmerProfileORM.owner_user_id == normalized_user_id) | (FarmerProfileORM.farmer_id == normalized_user_id)
            )
        ).scalars().all()
        for profile in profile_rows:
            session.delete(profile)
        session.delete(account)
        session.commit()
    try:
        delete_profile_store(normalized_user_id)
    except Exception:
        # 文件/双写模式兼容删除，忽略不存在或兼容层失败。
        pass
    return {"ok": True, "user_id": normalized_user_id}


@app.get("/api/admin/accounts/experts")
def list_active_experts(request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    with get_db_session() as session:
        rows = session.execute(
            select(UserAccountORM)
            .where(UserAccountORM.role == "EXPERT", UserAccountORM.status == "ACTIVE")
            .order_by(UserAccountORM.user_id.asc())
        ).scalars().all()
    return {
        "items": [
            {"user_id": row.user_id, "display_name": row.display_name}
            for row in rows
        ]
    }


@app.get("/api/expert-reviews/pending")
def get_pending_expert_reviews(request: Request, limit: int = 20) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_expert(actor)
    safe_limit = max(1, min(100, int(limit)))
    events = list_events(200000)
    latest_events = _pick_latest_case_by_trace(events)
    pending = [event for event in latest_events if _derive_review_task_status(event) == "ASSIGNED"]
    if not _is_admin(actor):
        actor_id = str(actor.get("user_id") or "").strip()
        pending = [
            event for event in pending
            if str(event.get("assigned_expert_id") or "").strip() == actor_id
        ]
    items = [_build_expert_review_list_item(event) for event in pending[:safe_limit]]
    return {
        "count": len(pending),
        "items": items,
    }


@app.get("/api/expert-reviews/{trace_id}")
def get_expert_review_case_detail(trace_id: str, request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_expert(actor)
    event = _latest_case_event_by_trace(trace_id)
    if not event:
        raise HTTPException(status_code=404, detail="病例不存在")
    if not _is_admin(actor):
        actor_id = str(actor.get("user_id") or "").strip()
        if str(event.get("assigned_expert_id") or "").strip() != actor_id:
            raise HTTPException(status_code=403, detail="当前病例未分配给你")
    return {"item": _build_expert_review_detail(event)}


@app.post("/api/expert-reviews/{trace_id}/submit")
def submit_expert_review(trace_id: str, request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_expert(actor)
    event = _latest_case_event_by_trace(trace_id)
    if not event:
        raise HTTPException(status_code=404, detail="病例不存在")
    if not _is_admin(actor):
        actor_id = str(actor.get("user_id") or "").strip()
        if str(event.get("assigned_expert_id") or "").strip() != actor_id:
            raise HTTPException(status_code=403, detail="当前病例未分配给你")

    confirmed_disease = str(payload.get("expert_review_result") or "").strip()
    if not confirmed_disease:
        raise HTTPException(status_code=400, detail="expert_review_result 不能为空")
    supplement_symptoms = sanitize_user_text(payload.get("expert_review_supplement_symptoms"))
    review_notes = sanitize_user_text(payload.get("expert_review_notes"))
    regenerate_treatment = bool(payload.get("regenerate_treatment", True))

    next_event = _clone_case_event_for_append(event)
    next_event["final_disease"] = confirmed_disease
    next_event["status"] = "completed"
    next_event["assigned_expert_id"] = actor.get("user_id") or event.get("assigned_expert_id")
    next_event["expert_review_status"] = "COMPLETED"
    next_event["expert_review_selected"] = True
    next_event["expert_review_result"] = confirmed_disease
    next_event["expert_review_supplement_symptoms"] = supplement_symptoms
    next_event["expert_review_notes"] = review_notes
    next_event["expert_reviewed_at"] = next_event["ts"]
    next_event["expert_review_recommended"] = False
    next_event["manual_review_recommended"] = False
    next_event["manual_review_required_before_execution"] = False
    next_event["expert_review_actions"] = []
    next_event["confirm_message"] = "专家已确认，方案已更新"

    if regenerate_treatment:
        treatment, personalization_outputs = _build_degraded_treatment(
            confirmed_disease,
            {
                "farm_scale": _safe_record(next_event.get("meta")).get("farm_scale"),
                "pesticide_access_level": _safe_record(next_event.get("meta")).get("pesticide_access_level"),
                "equipment": _safe_record(next_event.get("meta")).get("equipment") or [],
                "cultivation_mode": _safe_record(next_event.get("meta")).get("cultivation_mode"),
            },
        )
        if treatment is not None:
            next_event["treatment"] = {
                "plan": treatment.plan,
                "prevention": treatment.prevention,
            }
            next_event["treatment_available"] = True
            next_event["graph_treatment_generated"] = True
            if isinstance(personalization_outputs, dict):
                next_event["selected_branch"] = personalization_outputs.get("selected_branch") or next_event.get("selected_branch")

    append_event(serialize_final_response(next_event))
    return {"item": _serialize_admin_review_detail(next_event)}


@app.get("/api/admin/system-config")
def get_admin_system_config(request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    config = load_admin_runtime_config()
    return {"config": config, "llm_runtime_snapshot": get_admin_llm_runtime_snapshot(config)}


@app.put("/api/admin/system-config")
def update_admin_system_config(request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    next_config = save_admin_runtime_config(payload if isinstance(payload, dict) else {})
    return {"config": next_config, "llm_runtime_snapshot": get_admin_llm_runtime_snapshot(next_config)}


@app.get("/api/admin/reviews")
def list_admin_reviews(request: Request, status: str = "pending", limit: int = 50) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    safe_limit = max(1, min(200, int(limit)))
    expected = str(status or "pending").strip().lower()
    if expected not in {"pending", "assigned", "completed"}:
        raise HTTPException(status_code=400, detail="status 仅支持 pending / assigned / completed")
    latest_events = _pick_latest_case_by_trace(list_events(200000))
    filtered = [event for event in latest_events if _admin_review_bucket(event) == expected]
    items = [_serialize_admin_review_item(event) for event in filtered[:safe_limit]]
    return {"count": len(filtered), "items": items}


@app.get("/api/admin/reviews/{trace_id}")
def get_admin_review_detail(trace_id: str, request: Request) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    event = _latest_case_event_by_trace(trace_id)
    if not event:
        raise HTTPException(status_code=404, detail="病例不存在")
    detail = _serialize_admin_review_detail(event)
    detail["review_bucket"] = _admin_review_bucket(event)
    return {"item": detail}


@app.post("/api/admin/reviews/{trace_id}/assign")
def assign_admin_review(trace_id: str, request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    event = _latest_case_event_by_trace(trace_id)
    if not event:
        raise HTTPException(status_code=404, detail="病例不存在")
    expert_id = str(payload.get("assigned_expert_id") or "").strip()
    if not expert_id:
        raise HTTPException(status_code=400, detail="assigned_expert_id 不能为空")

    next_event = _clone_case_event_for_append(event)
    next_event["assigned_expert_id"] = expert_id
    if _derive_review_task_status(next_event) not in {"COMPLETED", "CANCELLED"}:
        next_event["expert_review_status"] = "PENDING"
        next_event["status"] = "pending_expert_review"
    note_value = payload.get("admin_note") if payload.get("admin_note") is not None else payload.get("review_flow_note")
    next_event["review_flow_note"] = sanitize_user_text(note_value) or next_event.get("review_flow_note")
    append_event(serialize_final_response(next_event))
    detail = _serialize_admin_review_detail(next_event)
    detail["review_bucket"] = _admin_review_bucket(next_event)
    return {"item": detail}


@app.post("/api/admin/reviews/{trace_id}/flow-status")
def update_admin_review_flow_status(trace_id: str, request: Request, payload: dict = Body(...)) -> dict[str, Any]:
    actor = _get_request_actor(request)
    _require_admin(actor)
    event = _latest_case_event_by_trace(trace_id)
    if not event:
        raise HTTPException(status_code=404, detail="病例不存在")
    flow_raw = payload.get("admin_flag") if payload.get("admin_flag") is not None else payload.get("review_flow_status")
    flow_status = _normalize_admin_flag(flow_raw)
    if flow_status not in {"normal", "abnormal", "closed"}:
        raise HTTPException(status_code=400, detail="review_flow_status 仅支持 normal / abnormal / closed")

    next_event = _clone_case_event_for_append(event)
    next_event["review_flow_status"] = flow_status
    note_value = payload.get("admin_note") if payload.get("admin_note") is not None else payload.get("review_flow_note")
    next_event["review_flow_note"] = sanitize_user_text(note_value)
    if flow_status == "closed":
        next_event["status"] = "cancelled"
    append_event(serialize_final_response(next_event))
    detail = _serialize_admin_review_detail(next_event)
    detail["review_bucket"] = _admin_review_bucket(next_event)
    return {"item": detail}




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


def _should_close_trace_stream(stream_event: dict[str, Any]) -> bool:
    if stream_event.get("node") == "Final" and stream_event.get("status") in {"end", "error"}:
        return True
    if stream_event.get("node") == "AwaitUserConfirmation" and stream_event.get("status") == "end":
        return True
    return False


@app.get("/api/traces/{trace_id}/stream")
async def stream_trace(trace_id: str):
    async def event_generator():
        queue = subscribe_trace(trace_id)
        try:
            history = list_trace_events(trace_id)
            for event in history:
                stream_event = _to_stream_event(trace_id, event)
                yield f"event: trace\ndata: {json.dumps(stream_event, ensure_ascii=False)}\n\n"
                if _should_close_trace_stream(stream_event):
                    return
            while True:
                event = await queue.get()
                stream_event = _to_stream_event(trace_id, event)
                yield f"event: trace\ndata: {json.dumps(stream_event, ensure_ascii=False)}\n\n"
                if _should_close_trace_stream(stream_event):
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


def _event_farmer_name(event: dict[str, Any]) -> str:
    meta = _safe_record(event.get("meta"))
    return str(meta.get("farmer_name") or meta.get("name") or event.get("farmer_name") or "").strip()


def _event_top1(event: dict[str, Any]) -> str:
    image_result = _safe_record(event.get("image_result"))
    top3 = _normalize_top3_candidates(image_result.get("top3"))
    if top3:
        return str(top3[0][0]).strip()
    return str(image_result.get("disease") or event.get("final_disease") or "未知").strip() or "未知"


def _pick_latest_case_by_trace(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        trace_id = str(event.get("trace_id") or "").strip()
        if not trace_id or trace_id in latest:
            continue
        latest[trace_id] = event
    return list(latest.values())


def _build_expert_review_list_item(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "trace_id": event.get("trace_id"),
        "case_id": event.get("id"),
        "submitted_at": event.get("ts"),
        "farmer_id": _event_farmer_id(event),
        "farmer_name": _event_farmer_name(event),
        "top1_disease": _event_top1(event),
        "status": event.get("status"),
        "expert_review_status": event.get("expert_review_status") or "NONE",
        "assigned_expert_id": event.get("assigned_expert_id"),
    }


def _derive_review_task_status(event: dict[str, Any]) -> str:
    review_flow_status = _normalize_admin_flag(event.get("review_flow_status"))
    case_status = str(event.get("status") or "").strip().lower()
    expert_status = str(event.get("expert_review_status") or "").strip().upper()
    assigned_expert_id = str(event.get("assigned_expert_id") or "").strip()

    if not _has_review_context(event):
        return "UNNEEDED"
    if review_flow_status == "closed" or case_status == "cancelled":
        return "CANCELLED"
    if expert_status == "COMPLETED":
        return "COMPLETED"
    if case_status == "pending_expert_review" and assigned_expert_id:
        return "ASSIGNED"
    if case_status == "pending_expert_review" and not assigned_expert_id:
        return "UNASSIGNED"
    if expert_status == "DECLINED":
        return "UNNEEDED"
    return "UNNEEDED"


def _has_review_context(event: dict[str, Any]) -> bool:
    case_status = str(event.get("status") or "").strip().lower()
    expert_status = str(event.get("expert_review_status") or "").strip().upper()
    assigned_expert_id = str(event.get("assigned_expert_id") or "").strip()
    expert_review_result = str(event.get("expert_review_result") or "").strip()
    if case_status == "pending_expert_review":
        return True
    if expert_status in {"PENDING", "COMPLETED", "DECLINED"}:
        return True
    if assigned_expert_id:
        return True
    if expert_review_result:
        return True
    return False


def _normalize_admin_flag(value: Any) -> str:
    flag = str(value or "").strip().lower()
    if flag in {"normal", "abnormal", "closed"}:
        return flag
    return "normal"


def _serialize_admin_review_item(event: dict[str, Any]) -> dict[str, Any]:
    base = _build_expert_review_list_item(event)
    case_status = str(event.get("status") or "").strip()
    review_task_status = _derive_review_task_status(event)
    admin_flag = _normalize_admin_flag(event.get("review_flow_status"))
    admin_note = event.get("review_flow_note")
    return {
        **base,
        "case_status": case_status,
        "review_task_status": review_task_status,
        "admin_flag": admin_flag,
        "admin_note": admin_note,
        # 保持向后兼容
        "review_flow_status": admin_flag,
        "review_flow_note": admin_note,
        "updated_at": event.get("ts"),
    }


def _serialize_admin_review_detail(event: dict[str, Any]) -> dict[str, Any]:
    detail = _build_expert_review_detail(event)
    case_status = str(event.get("status") or "").strip()
    review_task_status = _derive_review_task_status(event)
    admin_flag = _normalize_admin_flag(event.get("review_flow_status"))
    admin_note = event.get("review_flow_note")
    detail.update({
        "case_status": case_status,
        "review_task_status": review_task_status,
        "admin_flag": admin_flag,
        "admin_note": admin_note,
        # 保持向后兼容
        "review_flow_status": admin_flag,
        "review_flow_note": admin_note,
        "updated_at": event.get("ts"),
    })
    return detail


def _build_expert_review_detail(event: dict[str, Any]) -> dict[str, Any]:
    meta = _safe_record(event.get("meta"))
    image_result = _safe_record(event.get("image_result"))
    image_top3 = _normalize_top3_candidates(image_result.get("top3"))
    text_top3 = _normalize_top3_candidates(event.get("text_top3"))
    fusion_top3 = _normalize_top3_candidates(event.get("fusion_top3"))
    diagnosis_evidence = _safe_record(event.get("diagnosis_evidence"))
    return {
        **_build_expert_review_list_item(event),
        "image_url": event.get("image_url") or (f"/uploads/{event.get('image_id')}" if event.get("image_id") else None),
        "symptoms": event.get("symptoms") if isinstance(event.get("symptoms"), list) else [],
        "symptoms_text": "，".join([str(item).strip() for item in _as_clean_list(event.get("symptoms")) if str(item).strip()]),
        "crop_type": event.get("crop_type"),
        "growth_stage": meta.get("growth_stage") or event.get("growth_stage"),
        "base_id": meta.get("base_id") or event.get("base_id"),
        "base_name": meta.get("base_name") or event.get("base_name"),
        "environment": meta.get("environment"),
        "profile_summary": {
            "farm_scale": meta.get("farm_scale"),
            "pesticide_access_level": meta.get("pesticide_access_level"),
            "equipment": meta.get("equipment") if isinstance(meta.get("equipment"), list) else [],
            "cultivation_mode": meta.get("cultivation_mode"),
        },
        "model_outputs": {
            "image_top3": [[name, prob] for name, prob in image_top3],
            "text_top3": [[name, prob] for name, prob in text_top3],
            "fusion_top3": [[name, prob] for name, prob in fusion_top3],
            "final_confidence": event.get("final_confidence") or diagnosis_evidence.get("final_confidence"),
            "modality_conflict_flag": event.get("modality_conflict_flag"),
        },
        "expert_review_selected": event.get("expert_review_selected") is True,
        "expert_review_result": event.get("expert_review_result"),
        "expert_review_supplement_symptoms": event.get("expert_review_supplement_symptoms"),
        "expert_review_notes": event.get("expert_review_notes"),
        "expert_reviewed_at": event.get("expert_reviewed_at"),
        "review_flow_status": str(event.get("review_flow_status") or "normal"),
        "review_flow_note": event.get("review_flow_note"),
    }


def _admin_review_bucket(event: dict[str, Any]) -> str | None:
    review_task_status = _derive_review_task_status(event)
    if review_task_status == "UNASSIGNED":
        return "pending"
    if review_task_status == "ASSIGNED":
        return "assigned"
    if review_task_status == "COMPLETED":
        return "completed"
    return None


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


ANALYTICS_TERMINAL_CASE_STATUSES = {"completed", "cancelled"}
ANALYTICS_NON_TERMINAL_CASE_STATUSES = {
    "pending_expert_review",
    "waiting_for_supplement",
    "waiting_for_expert_decision",
}


def _is_terminal_case_status(status: str | None, *, include_cancelled: bool = True) -> bool:
    # 统计口径说明：
    # - 默认纳入 completed 与 cancelled，两者都代表病例主流程已终结；
    # - cancelled 仍会影响 summary/disease/timeseries 等聚合指标，便于运营看见“终止病例”体量。
    normalized = str(status or "").strip().lower()
    if normalized == "completed":
        return True
    if include_cancelled and normalized in ANALYTICS_TERMINAL_CASE_STATUSES:
        return True
    return False


def _include_event_in_analytics(event: dict[str, Any], include_non_terminal: bool = False) -> bool:
    if include_non_terminal:
        return True
    status = str(event.get("status") or "").strip().lower()
    return _is_terminal_case_status(status, include_cancelled=True)


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
    include_non_terminal: bool = False,
) -> list[dict[str, Any]]:
    events = list_events_range(start, end, 200000) if (start or end) else list_events(200000)
    return [
        event for event in events
        if _event_in_filters(event, farmer_id, base_id, disease, model_id, selected_branch, personalization_status)
        and _include_event_in_analytics(event, include_non_terminal=include_non_terminal)
    ]


def _scoped_farmer_query(request: Request, farmer_id: str | None) -> str | None:
    actor = _get_request_actor(request)
    return _apply_farmer_scope(actor, farmer_id)


@app.get("/api/stats/disease")
def get_disease_stats(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    effective_start = start
    effective_end = end
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    safe_days = max(1, min(3650, int(days)))
    if not effective_start and not effective_end:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=safe_days - 1)
        effective_start = start_date.isoformat()
        effective_end = end_date.isoformat()
    if any([farmer_id, base_id, disease, model_id, selected_branch, personalization_status]):
        events = _load_filtered_events(effective_start, effective_end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
        counts: dict[str, int] = {}
        for event in events:
            disease_name = _event_disease(event)
            counts[disease_name] = counts.get(disease_name, 0) + 1
    else:
        events = _load_filtered_events(effective_start, effective_end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
        counts: dict[str, int] = {}
        for event in events:
            disease_name = _event_disease(event)
            counts[disease_name] = counts.get(disease_name, 0) + 1
    items = [{"disease": disease_name, "count": count} for disease_name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)]
    return {"items": items}


@app.get("/api/stats/timeseries")
def get_timeseries(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    effective_start = start
    effective_end = end
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    safe_days = max(1, min(3650, int(days)))
    if not effective_start and not effective_end:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=safe_days - 1)
        effective_start = start_date.isoformat()
        effective_end = end_date.isoformat()
    events = _load_filtered_events(effective_start, effective_end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
    counts: dict[str, int] = {}
    for event in events:
        ts = event.get("ts")
        if not isinstance(ts, str):
            continue
        day = ts.split("T", 1)[0]
        counts[day] = counts.get(day, 0) + 1
    items = [{"date": day, "count": counts[day]} for day in sorted(counts.keys())]
    return {"items": items}


@app.get("/api/stats/geo")
def get_geo_stats(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    days: int = 30,
) -> dict[str, Any]:
    scoped_farmer_id = _scoped_farmer_query(request, None)
    if scoped_farmer_id:
        events = _load_filtered_events(start, end, scoped_farmer_id, None, None, None, None, None)
        points = []
        for event in events:
            meta = _safe_record(event.get("meta"))
            lat = meta.get("lat")
            lon = meta.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                points.append({"lat": float(lat), "lon": float(lon), "count": 1})
        return {"items": points}
    if start or end:
        if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
            raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
        return {"items": geo_points_range(start, end)}
    safe_days = max(1, min(3650, int(days)))
    return {"items": geo_points(safe_days)}


@app.get("/api/stats/models")
def get_model_stats(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)

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
    request: Request,
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, float | int]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")

    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
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
    request: Request,
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
    counts: dict[str, int] = {}
    for event in events:
        for reason in _event_filtered_reasons(event):
            counts[reason] = counts.get(reason, 0) + 1
    items = [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8]]
    return {"items": items}


@app.get("/api/stats/by-farmer")
def get_stats_by_farmer(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    base_id: str | None = None,
    disease: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    scoped_farmer_id = _scoped_farmer_query(request, None)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, scoped_farmer_id, base_id, disease, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
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
    request: Request,
    start: str | None = None,
    end: str | None = None,
    farmer_id: str | None = None,
    model_id: str | None = None,
    selected_branch: str | None = None,
    personalization_status: str | None = None,
    include_non_terminal: bool = False,
) -> dict[str, Any]:
    farmer_id = _scoped_farmer_query(request, farmer_id)
    if (start and not validate_date_str(start)) or (end and not validate_date_str(end)):
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD")
    events = _load_filtered_events(start, end, farmer_id, None, None, model_id, selected_branch, personalization_status, include_non_terminal=include_non_terminal)
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


@app.get("/cases")
def get_cases_page() -> Response:
    return serve_frontend_index()


@app.get("/kb")
def get_kb_page() -> Response:
    return serve_frontend_index()


@app.get("/kb/{name:path}")
def get_kb_detail_page(name: str) -> Response:
    if not name.strip():
        raise HTTPException(status_code=404, detail="Not Found")
    return serve_frontend_index()


@app.get("/expert-review")
def get_expert_review_page() -> Response:
    return serve_frontend_index()


@app.get("/admin/{name:path}")
def get_admin_page(name: str) -> Response:
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
def create_kb_disease(request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def update_kb_disease(name: str, request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def delete_kb_diseases(request: Request, payload: dict = Body(...)) -> dict:
    _require_admin(_get_request_actor(request))
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
def create_kb_treatments(request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def update_kb_treatments(disease: str, request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def delete_kb_treatments(request: Request, payload: dict = Body(...)) -> dict:
    _require_admin(_get_request_actor(request))
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
def create_kb_rule(request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def delete_kb_rules(request: Request, payload: dict = Body(...)) -> dict:
    _require_admin(_get_request_actor(request))
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="参数非法")
    rule_ids = payload.get("rule_ids")
    if not isinstance(rule_ids, list) or not rule_ids:
        raise HTTPException(status_code=400, detail="规则列表不能为空")
    deleted = kb.delete_rules([str(item).strip() for item in rule_ids if str(item).strip()])
    return {"ok": True, "deleted": deleted}


@app.put("/api/kb/rules/{rule_id}")
def update_kb_rule(rule_id: str, request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def create_kb_symptom_map(request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def update_kb_symptom_map(symptom: str, request: Request, payload: dict = Body(...)) -> dict[str, bool]:
    _require_admin(_get_request_actor(request))
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
def delete_kb_symptom_map(request: Request, payload: dict = Body(...)) -> dict:
    _require_admin(_get_request_actor(request))
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
