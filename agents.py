"""
智能体节点模块
定义各个智能体的具体实现
"""
from state import CropDiseaseState
from llm_utils import call_llm, extract_json_from_response
from diagnosis_model import build_reliability_summary, get_diagnosis_engine, evaluate_confirmation_decision
from knowledge_base import get_kb_manager
from config import DIAGNOSIS_ALLOW_TORCH
from runtime_settings import get_admin_flag, get_runtime_thresholds
from confidence_policy import make_confidence_flags
from personalization.profile_models import FarmerProfile, BaseProfile, TreatmentConstraint
from personalization.profile_rules import apply_personalization_to_treatment, normalize_filter_outputs
from personalization.profile_constants import normalize_growth_stage
from personalization.utils import (
    dedupe_reasons,
    compute_personalization_applied,
    build_missing_field_questions,
    normalize_follow_up_questions,
)
from trace_store import append_trace_event
from datetime import datetime, timezone
from typing import Optional
from typing import Any
from model_registry import resolve_model
from pydantic import BaseModel, Field, ValidationError
import re
import json
import os
from pathlib import Path
from follow_up_rules import FOLLOW_UP_RULES
class _LazyKBManagerProxy:
    def __getattr__(self, item: str):
        return getattr(get_kb_manager(), item)


# 获取知识库管理器实例（延迟初始化，避免模块导入时强制连接持久化后端）
kb_manager = _LazyKBManagerProxy()

def _canonicalize_growth_stage(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = normalize_growth_stage(text)
    return normalized or text

VERIFICATION_SYSTEM_PROMPT = """
你是一名严格的农业安全审查员（Verification Agent）。

你的职责不是重新诊断病害，而是审查“治疗方案”和“预防建议”是否安全、合规、可执行。

你必须重点检查：
1. 是否包含禁用农药、禁用成分或明显高风险用药建议；
2. 是否违反采收安全间隔要求；
3. 是否与农户档案约束冲突（如购药能力、设备能力、家庭级/中等规模/企业级分档）；
4. 是否忽略关键环境风险（如高湿、连阴雨、棚内通风差、临近采收）；
5. 是否存在模糊、不可执行或容易误导用户的表述；
6. 是否遗漏必要的安全提醒、复查建议、预防复发建议。

审查原则：
- 必须优先依据结构化字段做判断，不能凭空编造农业规范。
- 如果信息不足，可以指出“信息不足导致无法完全审查”，但不能假装通过。
- 如果发现问题，不要直接重写方案，而是给出“必须修改点”。
- 输出必须严格为 JSON，不要输出额外解释。

输出 JSON schema：
{
  "passed": true,
  "risk_level": "low|medium|high",
  "issues": ["..."],
  "must_fix": ["..."],
  "suggested_rewrite_points": ["..."],
  "compliance_summary": "..."
}
"""

TREATMENT_REWRITE_SYSTEM_PROMPT = """
你是一名番茄病害治疗方案重写助手。
上一版方案未通过农业合规审查，请根据审查意见重写。
你必须逐项满足 must_fix，不能忽略任何一条。
输出必须严格为 JSON，不要输出额外解释。
"""


def _diag_debug_enabled(state: CropDiseaseState) -> bool:
    flags = state.get("personalization_flags", {}) if isinstance(state, dict) else {}
    return str(os.getenv("DIAG_DEBUG_RUNTIME", "0")).lower() in {"1", "true", "yes"} or bool(flags.get("debug_runtime"))
class TreatmentPlanBranches(BaseModel):
    FAMILY: list[str] = Field(default_factory=list)
    MID: list[str] = Field(default_factory=list)
    ENTERPRISE: list[str] = Field(default_factory=list)
class TreatmentLLMOutput(BaseModel):
    overview: str
    immediate_actions: list[str] = Field(default_factory=list)
    treatment_plan: TreatmentPlanBranches
    prevention_plan: list[str] = Field(default_factory=list)
    resistance_management: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)
    follow_up: list[str] = Field(default_factory=list)
    personalization_reasons: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
def append_trace(
    state: CropDiseaseState,
    agent: str,
    inputs: dict,
    outputs: dict,
    decision: dict | str | None = None,
) -> None:
    trace_id = state.get("trace_id")
    event = {
        "agent": agent,
        "inputs": inputs,
        "outputs": outputs,
        "step": state.get("current_step"),
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "trace_id": trace_id,
    }
    if decision is not None:
        event["decision"] = decision
    state.setdefault("trace_events", []).append(event)
    if trace_id:
        append_trace_event(trace_id, dict(event))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_top3_candidates(candidates: Any) -> list[tuple[str, float]]:
    normalized: list[tuple[str, float]] = []
    if not isinstance(candidates, list):
        return normalized
    for item in candidates:
        disease = ""
        prob = None
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            disease = str(item[0] or "").strip()
            prob = _safe_float(item[1])
        elif isinstance(item, dict):
            disease = str(item.get("disease") or item.get("label") or item.get("name") or "").strip()
            prob = _safe_float(item.get("prob"))
            if prob is None:
                prob = _safe_float(item.get("confidence"))
        if disease and prob is not None:
            normalized.append((disease, float(prob)))
    return normalized


def confirm_input_step(state: CropDiseaseState) -> CropDiseaseState:
    # 即使 incoming_symptoms 是空列表，也要使用它
    incoming_symptoms = [str(item).strip() for item in (state.get("incoming_symptoms") or []) if str(item).strip()]
    historical_symptoms = [str(item).strip() for item in (state.get("historical_symptoms") or []) if str(item).strip()]
    merged: list[str] = []
    for symptom in [*historical_symptoms, *incoming_symptoms]:
        if symptom and symptom not in merged:
            merged.append(symptom)
    image_path = state.get("image_path") or state.get("image")
    state["symptoms"] = merged
    try:
        state["normalized_symptoms"] = kb_manager.normalize_symptoms(merged)
    except Exception:
        state["normalized_symptoms"] = list(merged)
    if image_path:
        state["image_path"] = str(image_path)
    state["supplement_mode"] = "confirm_input"
    state["current_step"] = "confirm_input"
    state["next_action"] = "diagnosis"
    append_trace(
        state,
        agent="confirm_input",
        inputs={
            "symptoms": state.get("symptoms"),
            "incoming_symptoms": incoming_symptoms,
            "historical_symptoms": historical_symptoms,
            "image_path": state.get("image_path"),
            "previous_trace_id": state.get("previous_trace_id"),
            "confirm_round_parent_trace_id": state.get("confirm_round_parent_trace_id"),
        },
        outputs={
            "symptoms": merged,
            "normalized_symptoms": state.get("normalized_symptoms"),
            "image_path": state.get("image_path"),
            "next_action": "diagnosis",
        },
    )
    return state


def confirm_choice_step(state: CropDiseaseState) -> CropDiseaseState:
    selected = str(state.get("selected_candidate") or state.get("user_choice") or "").strip()
    inherited = state.get("inherited_context") if isinstance(state.get("inherited_context"), dict) else {}
    fusion_top3 = _normalize_top3_candidates(state.get("fusion_top3")) or _normalize_top3_candidates(inherited.get("fusion_top3"))
    image_result = state.get("image_result") if isinstance(state.get("image_result"), dict) else {}
    inherited_image_result = inherited.get("image_result") if isinstance(inherited.get("image_result"), dict) else {}
    inherited_image_diagnosis = inherited.get("image_diagnosis") if isinstance(inherited.get("image_diagnosis"), dict) else {}
    image_top3 = (
        _normalize_top3_candidates(image_result.get("top3"))
        or _normalize_top3_candidates(inherited_image_result.get("top3"))
        or _normalize_top3_candidates(inherited.get("image_top3"))
        or _normalize_top3_candidates(inherited_image_diagnosis.get("top3"))
    )
    diagnosis_evidence = state.get("diagnosis_evidence") if isinstance(state.get("diagnosis_evidence"), dict) else {}
    if not diagnosis_evidence and isinstance(inherited.get("diagnosis_evidence"), dict):
        diagnosis_evidence = dict(inherited.get("diagnosis_evidence"))
    text_top3 = _normalize_top3_candidates(state.get("text_top3")) or _normalize_top3_candidates(inherited.get("text_top3"))
    evidence_top3 = (
        _normalize_top3_candidates(diagnosis_evidence.get("fusion_top3"))
        or _normalize_top3_candidates(diagnosis_evidence.get("image_top3"))
        or _normalize_top3_candidates(diagnosis_evidence.get("text_top3"))
        or text_top3
    )
    confidence = None
    for candidates in (fusion_top3, image_top3, evidence_top3):
        for disease, prob in candidates:
            if disease == selected and prob > 0:
                confidence = float(prob)
                break
        if confidence is not None:
            break
    if confidence is None:
        for raw in (
            state.get("final_confidence"),
            inherited.get("final_confidence"),
            image_result.get("confidence"),
            inherited.get("image_confidence"),
            state.get("image_confidence"),
            inherited.get("text_confidence"),
            state.get("text_confidence"),
            diagnosis_evidence.get("final_confidence"),
        ):
            value = _safe_float(raw)
            if value is not None and value > 0:
                confidence = value
                break
    if confidence is None or confidence <= 0:
        state["workflow_error"] = "confirm_choice_confidence_missing"
        state["error"] = "confirm_choice_confidence_missing"
        state["next_action"] = "end"
        append_trace(
            state,
            agent="confirm_choice",
            inputs={"selected_candidate": selected},
            outputs={"error": "confirm_choice_confidence_missing"},
            decision={"next_action": "end", "reason": "confirm_choice_confidence_missing"},
        )
        return state

    state["final_disease"] = selected
    state["disease_type"] = selected
    state["final_source"] = "user_confirmed_candidate"
    state["final_confidence"] = confidence
    state["disease_confidence"] = confidence
    if fusion_top3:
        state["fusion_top3"] = fusion_top3
    if text_top3:
        state["text_top3"] = text_top3
    if image_top3:
        merged_image = dict(inherited_image_result)
        merged_image.update(image_result)
        merged_image["top3"] = [{"disease": d, "prob": p, "prob_pct": round(p * 100, 2)} for d, p in image_top3]
        if not merged_image.get("disease"):
            merged_image["disease"] = image_top3[0][0]
        merged_confidence = _safe_float(merged_image.get("confidence"))
        if merged_confidence is None or merged_confidence <= 0:
            merged_image["confidence"] = image_top3[0][1]
        state["image_result"] = merged_image
    if diagnosis_evidence:
        state["diagnosis_evidence"] = diagnosis_evidence
    for field in ("modality_conflict_flag", "image_reliable", "text_reliable", "supplement_mode", "fusion_meta", "image_confidence", "text_confidence"):
        if state.get(field) is None and inherited.get(field) is not None:
            state[field] = inherited.get(field)
    if not state.get("reliability_issue_types") and inherited.get("reliability_issue_types") is not None:
        state["reliability_issue_types"] = list(inherited.get("reliability_issue_types") or [])
    inherited_meta = inherited.get("meta") if isinstance(inherited.get("meta"), dict) else {}
    model_meta = {
        "model_id": inherited_meta.get("model_id") or inherited.get("model_id"),
        "model_display_name": inherited_meta.get("model_display_name") or inherited.get("model_display_name"),
        "backend": inherited_meta.get("model_backend") or inherited.get("model_backend"),
        "resolved_model_path": inherited_meta.get("resolved_model_path") or inherited.get("resolved_model_path"),
        "model_fallback_reason": inherited_meta.get("model_fallback_reason") or inherited.get("model_fallback_reason") or [],
    }
    if any(model_meta.values()):
        state["diagnosis_model_meta"] = model_meta
        if model_meta.get("model_id"):
            state["diagnosis_model_id"] = model_meta.get("model_id")
    flags = dict(state.get("personalization_flags") or {})
    flags["need_confirm"] = False
    state["personalization_flags"] = flags
    state["confirmation_mode"] = "confirm_choice"
    state["current_step"] = "confirm_choice"
    state["next_action"] = "supervisor"
    append_trace(
        state,
        agent="confirm_choice",
        inputs={"selected_candidate": selected},
        outputs={
            "final_disease": selected,
            "final_confidence": confidence,
            "final_source": "user_confirmed_candidate",
            "need_confirm": False,
        },
    )
    return state
def _clean_query_for_symptoms(query: str) -> tuple[str, list[str]]:
    cleaned = query
    removed: list[str] = []
    patterns = [
        r"(作物类型|作物|crop)\s*[:：]\s*([^\s,，；;]+)",
        r"(图片路径|图像路径|图片|图像|path)\s*[:：]\s*([^\s,，；;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            removed.append(match.group(0))
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned, removed
def _resolve_image_path_fast(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    candidates: list[Path] = []
    text = str(raw_path).strip().strip('"').strip("'")
    if not text:
        return None
    raw = Path(text)
    candidates.append(raw)
    normalized_text = text.replace('\\', '/')
    normalized = Path(normalized_text)
    candidates.append(normalized)
    if normalized.name:
        upload_guess = Path('.cache') / 'uploads' / normalized.name
        candidates.append(upload_guess)
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            resolved = candidate
        if resolved.exists():
            return str(resolved)
        if candidate.exists():
            return str(candidate)
    return None
def reception_agent(state: CropDiseaseState) -> CropDiseaseState:
    """
    番茄病害接待智能体节点（使用大模型API）
    职责：
    1. 解析用户的番茄病害查询
    2. 提取番茄的生长阶段
    3. 识别番茄叶子的症状信息
    4. 提取番茄叶子图像路径（如果有）
    Args:
        state: 当前系统状态
    Returns:
        更新后的状态
    """
    print("\n[番茄病害接待智能体] 正在分析用户输入...")
    query = state["user_query"]
    profile, base_profile = _get_profile_from_state(state)
    
    # 提取图像路径（如果用户查询中包含）
    image_path = None
    import re
    
    # 支持多种图像路径格式
    image_patterns = [
        r'图像路径[:：]\s*(.+)',
        r'图片路径[:：]\s*(.+)',
        r'图像[:：]\s*(.+)',
        r'图片[:：]\s*(.+)',
        r'path[:：]\s*(.+)'  
    ]
    
    for pattern in image_patterns:
        match = re.search(pattern, query)
        if match:
            image_path = match.group(1).strip()
            # 从查询中移除图像路径部分
            query = re.sub(pattern, '', query).strip()
            break
    
    # 快速解析图像路径，避免全量 glob 导致接待阶段耗时飙升
    image_path = _resolve_image_path_fast(image_path)
    if not image_path and state.get("image_path"):
        image_path = _resolve_image_path_fast(str(state.get("image_path")))
    if not image_path:
        print("警告：图像路径不存在或不可解析")
    
    cleaned_query, removed_tokens = _clean_query_for_symptoms(query)
    # 使用大模型提取信息（专注于番茄）
    system_prompt = """你是一个专业的番茄病害信息提取助手。请从用户的番茄病害描述中提取以下信息：
1. 番茄的生长阶段（如：苗期、开花期、结果期等）
2. 番茄叶子的症状列表（如：发黄、斑点、腐烂、白粉、卷曲等）
请以JSON格式返回结果，格式如下：
{
    "growth_stage": "生长阶段（如果没有则返回null）",
    "symptoms": ["症状1", "症状2", ...]
}
注意：
- 只关注番茄相关的信息
- 如果用户没有提及具体生长阶段，返回null
- 如果没有提取到明确的症状，返回空列表
- 不要添加任何额外的解释或说明"""
    # 空文本或仅标点时跳过 LLM，降低接待延迟
    query_for_extract = cleaned_query.strip()
    if not query_for_extract or re.fullmatch(r"[，,。；;！？!？\s]+", query_for_extract):
        _, crop_growth_stage, symptoms = _fallback_extraction(query_for_extract)
    else:
        try:
            response = call_llm(query_for_extract, system_prompt, temperature=0.3)
            result = extract_json_from_response(response)
            if result:
                crop_growth_stage = result.get("growth_stage")
                symptoms = result.get("symptoms", [])
            else:
                # 如果JSON解析失败，使用规则匹配作为后备
                _, crop_growth_stage, symptoms = _fallback_extraction(query_for_extract)
        except Exception as e:
            print(f"大模型调用失败，使用规则匹配: {e}")
            _, crop_growth_stage, symptoms = _fallback_extraction(query_for_extract)
    crop_growth_stage = _canonicalize_growth_stage(crop_growth_stage)
    # 强制设置作物类型为番茄
    crop_type = "番茄"
    _fill_missing_from_profile(state, base_profile)
    policy = state.get("personalization_policy") or {}
    missing_profile_fields = _find_missing_profile_fields(profile, base_profile, policy)
    
    # 如果没有提取到症状，保持为空列表
    if not symptoms:
        symptoms = []
    message_parts = [
        f"番茄病害接待智能体：作物类型={crop_type}",
        f"生长阶段={crop_growth_stage}",
        f"症状={symptoms}",
    ]
    if image_path:
        message_parts.append(f"图像路径={image_path}")
    if missing_profile_fields:
        message_parts.append(f"档案缺失字段：{', '.join(missing_profile_fields)}，请后续追问补充。")
        flags = state.get("personalization_flags", {}) or {}
        flags["missing_profile_fields"] = missing_profile_fields
        follow_ups = normalize_follow_up_questions(
            _build_profile_follow_up_questions(missing_profile_fields, profile, base_profile, policy)
        )
        if follow_ups:
            profile_follow_ups = follow_ups[:3]
            state["profile_follow_up_questions"] = profile_follow_ups
            state["follow_up_questions"] = normalize_follow_up_questions(
                list(state.get("diagnosis_follow_up_questions") or []) + profile_follow_ups
            )
            flags["follow_up_questions"] = state["follow_up_questions"]
        state["personalization_flags"] = flags
    message = "，".join(message_parts)
    # 更新状态
    state["crop_type"] = crop_type
    state["crop_growth_stage"] = _canonicalize_growth_stage(crop_growth_stage)
    normalized_symptoms = kb_manager.normalize_symptoms(symptoms)
    state["symptoms"] = symptoms
    state["structured_symptoms"] = {"normalized_symptoms": normalized_symptoms}
    state["normalized_symptoms"] = normalized_symptoms
    state["image_path"] = image_path
    state["current_step"] = "reception_complete"
    state["next_action"] = None
    state["messages"] = [message]
    print(f"  - 作物类型: {crop_type}")
    print(f"  - 生长阶段: {crop_growth_stage}")
    print(f"  - 症状: {symptoms}")
    if image_path:
        print(f"  - 图像路径: {image_path}")
    append_trace(
        state,
        agent="reception",
        inputs={"user_query": state.get("user_query"), "cleaned_query": cleaned_query},
        outputs={
            "crop_type": crop_type,
            "crop_growth_stage": _canonicalize_growth_stage(crop_growth_stage),
            "symptoms": symptoms,
            "normalized_symptoms": normalized_symptoms,
            "image_path": image_path,
            "missing_profile_fields": missing_profile_fields,
            "removed_tokens": removed_tokens,
        },
    )
    return state
def _fallback_extraction(query: str):
    """规则匹配后备方案"""
    query_lower = query.lower()
    
    # 生长阶段关键词
    growth_stages = ["苗期", "开花期", "结果期", "成熟期", "生长前期", "生长中期", "生长后期"]
    crop_growth_stage = None
    for stage in growth_stages:
        if stage in query:
            crop_growth_stage = stage
            break
    
    # 症状关键词（专注于番茄病害）
    symptom_keywords = [
        "叶子发黄", "发黄", "枯萎", "斑点", "腐烂", "虫洞",
        "变色", "卷曲", "枯死", "长虫", "白粉", "霉斑",
        "叶片斑点", "果实腐烂", "生长缓慢", "植株矮小"
    ]
    symptoms = []
    for symptom in symptom_keywords:
        if symptom in query:
            symptoms.append(symptom)
    
    # 强制作物类型为番茄
    crop_type = "番茄"
    
    return crop_type, crop_growth_stage, symptoms
def diagnosis_agent(state: CropDiseaseState) -> CropDiseaseState:
    """番茄病害诊断智能体：KB 文本分支 + 图像分支 + 轻量先验融合。"""
    print("\n[番茄病害诊断智能体] 正在分析病害...")
    crop_type = state.get("crop_type", "番茄")
    symptoms = state.get("symptoms", []) or []
    crop_growth_stage = _canonicalize_growth_stage(state.get("crop_growth_stage"))
    image_path = state.get("image_path")
    flags = state.get("personalization_flags", {}) or {}
    flags["need_confirm"] = False
    diagnosis_reasons = {"low_confidence", "low_margin", "insufficient_evidence", "weak_image_text_conflict", "image_text_conflict", "both_modalities_weak"}
    existing_reasons = [str(item).strip() for item in (flags.get("fallback_reason") or []) if str(item).strip()]
    flags["fallback_reason"] = [reason for reason in existing_reasons if reason not in diagnosis_reasons]
    state["diagnosis_follow_up_questions"] = []
    state["follow_up_questions"] = normalize_follow_up_questions(
        list(state.get("profile_follow_up_questions") or [])
    )
    degraded_reasons: list[str] = []
    runtime_enable_personalization = bool(get_admin_flag("workflow.enable_personalization_agent", True))
    thresholds = get_runtime_thresholds()
    if not runtime_enable_personalization:
        flags = {}
        state["personalization_context"] = None
        state["personalization_reasons"] = []

    enable_image_model = bool(get_admin_flag("model_fusion.enable_image_model", True))
    enable_text_model = bool(get_admin_flag("model_fusion.enable_text_model", True))
    policy = state.get("personalization_policy") or {}
    hard_constraints = (policy.get("hard_constraints") or {}) if isinstance(policy, dict) else {}
    personalization_context = state.get("personalization_context")

    facility = state.get("facility") or flags.get("facility")
    province = state.get("province") or flags.get("province")
    environment = state.get("environment") or flags.get("environment")

    allow_torch = str(DIAGNOSIS_ALLOW_TORCH).lower() in {"1", "true", "yes"}
    resolved_model, fallback_reasons = resolve_model(state.get("diagnosis_model_id"), allow_torch=allow_torch)
    state["diagnosis_model_id"] = resolved_model.model_id
    diagnosis_engine = get_diagnosis_engine(
        model_path=resolved_model.model_path,
        backend=resolved_model.backend,
        allow_torch=allow_torch,
    )

    model_meta = {
        "model_id": resolved_model.model_id,
        "model_display_name": resolved_model.display_name,
        "backend": resolved_model.backend,
        "resolved_model_path": resolved_model.model_path,
        "model_fallback_reason": fallback_reasons,
    }
    state["diagnosis_model_meta"] = model_meta

    normalized_symptoms = kb_manager.normalize_symptoms(symptoms)
    state["structured_symptoms"] = {"normalized_symptoms": normalized_symptoms}
    state["normalized_symptoms"] = normalized_symptoms
    debug_enabled = _diag_debug_enabled(state)
    diagnosis_model_module = __import__("diagnosis_model")
    debug_payload: dict[str, object] = {
        "raw_symptoms": list(symptoms),
        "normalized_symptoms": list(normalized_symptoms),
        "predict_text_proba_version": getattr(diagnosis_model_module, "PREDICT_TEXT_PROBA_VERSION", "unknown"),
    }

    image_probs: dict[str, float] = {}
    text_probs: dict[str, float] = {}
    prior_probs: dict[str, float] = {}
    fusion_probs: dict[str, float] = {}
    image_confidence = 0.0

    # 图像分支
    if enable_image_model and image_path:
        try:
            if hasattr(diagnosis_engine, "predict_image_proba"):
                image_probs = diagnosis_engine.predict_image_proba(image_path)
                image_top3_tmp = sorted(image_probs.items(), key=lambda x: x[1], reverse=True)[:3]
                image_confidence = float(image_top3_tmp[0][1]) if image_top3_tmp else 0.0
            else:
                disease_type_legacy, conf_legacy, probs_legacy = diagnosis_engine.diagnose_from_image(image_path)
                image_confidence = float(conf_legacy or 0.0)
                for label, prob in (probs_legacy or {}).items():
                    disease = kb_manager.map_image_label_to_disease(label)
                    image_probs[disease] = image_probs.get(disease, 0.0) + float(prob)
                if not image_probs and disease_type_legacy:
                    image_probs[kb_manager.map_image_label_to_disease(disease_type_legacy)] = image_confidence

            image_top3 = sorted(image_probs.items(), key=lambda x: x[1], reverse=True)[:3]
            state["image_diagnosis"] = {
                "image_path": image_path,
                "top1": {
                    "disease": image_top3[0][0] if image_top3 else None,
                    "confidence": float(image_top3[0][1]) if image_top3 else 0.0,
                },
                "top3": [(name, float(prob)) for name, prob in image_top3],
            }
        except Exception as e:
            print(f"[番茄病害诊断智能体] 图像分支失败: {e}")
            image_probs = {}
            state["image_diagnosis"] = None
            degraded_reasons.append("image_branch_failed")
    elif not enable_image_model:
        image_probs = {}
        image_confidence = 0.0

    # 文本分支（KB 驱动）
    text_evidence_active = enable_text_model and kb_manager.has_effective_text_evidence(
        normalized_symptoms,
        growth_stage=crop_growth_stage,
        environment=environment,
        facility=facility,
        province=province,
    )
    text_probs_source = "none"
    try:
        if text_evidence_active and hasattr(diagnosis_engine, "predict_text_proba"):
            text_probs_source = "predict_text_proba"
            text_probs = diagnosis_engine.predict_text_proba(
                raw_text=state.get("user_query"),
                symptoms=normalized_symptoms,
                growth_stage=crop_growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )
        elif text_evidence_active:
            text_probs_source = "kb_score_diseases_from_text"
            text_probs = kb_manager.score_diseases_from_text(
                crop_type=crop_type,
                symptoms=normalized_symptoms,
                growth_stage=crop_growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )
        else:
            text_probs = {}
            text_probs_source = "none_no_effective_text_evidence"
    except Exception as e:
        print(f"[番茄病害诊断智能体] 文本分支失败: {e}")
        text_probs = {}
        text_probs_source = "exception"
        degraded_reasons.append("text_branch_failed")

    if not text_evidence_active:
        text_probs = {}
        text_probs_source = "none_no_effective_text_evidence"

    # 先验分支
    try:
        if hasattr(diagnosis_engine, "build_prior_proba"):
            prior_probs = diagnosis_engine.build_prior_proba(
                growth_stage=crop_growth_stage,
                facility=facility,
                province=province,
            )
    except Exception:
        prior_probs = {}
        degraded_reasons.append("prior_branch_failed")

    image_top3 = sorted(image_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    text_top3 = sorted(text_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    text_confidence = float(text_top3[0][1]) if text_top3 else 0.0

    if hasattr(diagnosis_engine, "fuse_multimodal_probs"):
        try:
            fusion_probs, fusion_meta = diagnosis_engine.fuse_multimodal_probs(
                image_probs=image_probs,
                text_probs=text_probs,
                prior_probs=prior_probs,
                image_confidence=image_confidence,
                text_confidence=text_confidence,
                text_evidence_active=text_evidence_active,
                normalized_symptoms=normalized_symptoms,
                image_quality_flags=state.get("image_quality_flags"),
                image_quality_hint=state.get("image_quality_hint"),
            )
        except TypeError:
            fusion_probs, fusion_meta = diagnosis_engine.fuse_multimodal_probs(
                image_probs=image_probs,
                text_probs=text_probs,
                prior_probs=prior_probs,
                image_confidence=image_confidence,
                text_confidence=text_confidence,
            )
    else:
        fusion_probs = image_probs or text_probs or prior_probs or {}
        fusion_meta = {"normalized_weights": {"image": 1.0 if image_probs else 0.0, "text": 1.0 if text_probs and not image_probs else 0.0, "prior": 0.0}}

    fusion_top3 = sorted(fusion_probs.items(), key=lambda x: x[1], reverse=True)[:3]

    image_top1 = image_top3[0][0] if image_top3 else None
    text_top1 = text_top3[0][0] if text_top3 else None
    final_disease = fusion_top3[0][0] if fusion_top3 else (image_top1 or text_top1 or "未知待确认")
    final_confidence = float(fusion_top3[0][1]) if fusion_top3 else max(image_confidence, text_confidence, 0.0)
    final_source = "fusion"
    insufficient_evidence = bool(
        not fusion_probs
        or (isinstance(fusion_meta, dict) and bool(fusion_meta.get("insufficient_evidence")))
    )
    if insufficient_evidence:
        final_disease = "未知待确认"
        final_confidence = 0.0
        final_source = "insufficient_evidence"
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", [])
        if "insufficient_evidence" not in flags["fallback_reason"]:
            flags["fallback_reason"].append("insufficient_evidence")
        if "no_active_evidence" not in degraded_reasons:
            degraded_reasons.append("no_active_evidence")

    fusion_conflict_reason = (fusion_meta.get("confidence_drop_reason") if isinstance(fusion_meta, dict) else None)
    has_image_active = (
        bool(fusion_meta.get("has_image"))
        if isinstance(fusion_meta, dict) and "has_image" in fusion_meta
        else bool(image_probs)
    )
    has_text_active = (
        bool(fusion_meta.get("has_text"))
        if isinstance(fusion_meta, dict) and "has_text" in fusion_meta
        else bool(text_probs)
    )
    image_reliable = (
        bool(fusion_meta.get("image_reliable"))
        if isinstance(fusion_meta, dict) and "image_reliable" in fusion_meta
        else bool(image_confidence >= float(thresholds["image_top1_threshold"]))
    )
    text_reliable = (
        bool(fusion_meta.get("text_reliable"))
        if isinstance(fusion_meta, dict) and "text_reliable" in fusion_meta
        else bool(text_confidence >= float(thresholds["text_top1_threshold"]))
    )
    fusion_case = (fusion_meta.get("fusion_case") if isinstance(fusion_meta, dict) else None) or "unknown"
    weak_conflict_candidate = bool(
        fusion_meta.get("weak_conflict_candidate")
        if isinstance(fusion_meta, dict)
        else False
    )
    weak_conflict_flag = bool(
        weak_conflict_candidate
        and final_confidence < float(thresholds["diagnosis_conf_threshold"])
    )
    top1_conflict = bool(
        has_image_active
        and has_text_active
        and image_reliable
        and text_reliable
        and image_top1
        and text_top1
        and image_top1 != text_top1
    )
    modality_conflict_flag = bool(top1_conflict)
    reliability_summary = build_reliability_summary(
        image_reliable=image_reliable,
        text_reliable=text_reliable,
        modality_conflict_flag=modality_conflict_flag,
    )
    reliability_issue_types = list(
        (fusion_meta.get("reliability_issue_types") if isinstance(fusion_meta, dict) else None)
        or reliability_summary["reliability_issue_types"]
    )
    supplement_mode = str(
        (fusion_meta.get("supplement_mode") if isinstance(fusion_meta, dict) else None)
        or reliability_summary["supplement_mode"]
    )
    if isinstance(fusion_meta, dict):
        fusion_meta["image_reliable"] = image_reliable
        fusion_meta["text_reliable"] = text_reliable
        fusion_meta["reliability_issue_types"] = reliability_issue_types
        fusion_meta["supplement_mode"] = supplement_mode

    debug_payload.update(
        {
            "text_evidence_active": bool(text_evidence_active),
            "text_probs_source": text_probs_source,
            "text_probs": dict(text_probs),
            "has_text": has_text_active,
            "text_reliable": text_reliable,
            "fusion_weights": (fusion_meta.get("normalized_weights") if isinstance(fusion_meta, dict) else {}),
            "confidence_drop_reason": fusion_conflict_reason,
            "fusion_case": fusion_case,
            "insufficient_evidence": insufficient_evidence,
            "fuse_version": (fusion_meta.get("fuse_version") if isinstance(fusion_meta, dict) else None),
            "modality_conflict_flag": modality_conflict_flag,
            "image_reliable": image_reliable,
            "text_reliable": text_reliable,
            "reliability_issue_types": reliability_issue_types,
            "supplement_mode": supplement_mode,
            "weak_conflict_candidate": weak_conflict_candidate,
            "weak_conflict_flag": weak_conflict_flag,
            "final_confidence": float(final_confidence),
        }
    )
    state["workflow_degraded"] = bool(degraded_reasons)
    state["degraded_reason"] = ",".join(dict.fromkeys(degraded_reasons)) or None
    debug_payload["workflow_degraded"] = state["workflow_degraded"]
    debug_payload["degraded_reason"] = state["degraded_reason"]
    # 记录易混淆处理结果
    image_confusion_result = fusion_meta.get("image_confusion_result") if isinstance(fusion_meta, dict) else None
    text_confusion_result = fusion_meta.get("text_confusion_result") if isinstance(fusion_meta, dict) else None
    
    if image_confusion_result and image_confusion_result.get("is_adjusted"):
        print(f"[易混淆处理] 图像模型预测调整: {image_confusion_result.get('adjustment_reason')}")
    if text_confusion_result and text_confusion_result.get("is_adjusted"):
        print(f"[易混淆处理] 文本模型预测调整: {text_confusion_result.get('adjustment_reason')}")
    adjusted_top3 = (fusion_meta.get("pre_fusion_top3_adjusted") if isinstance(fusion_meta, dict) else None) or {}
    image_top3_adjusted = list(adjusted_top3.get("image") or [])
    text_top3_adjusted = list(adjusted_top3.get("text") or [])
    if state.get("image_diagnosis") and image_top3_adjusted:
        state["image_diagnosis"]["top3_adjusted"] = [(name, float(prob)) for name, prob in image_top3_adjusted]

    if debug_enabled:
        print(f"[DiagnosisDebug] {json.dumps(debug_payload, ensure_ascii=False)}")

    if hasattr(diagnosis_engine, "build_diagnosis_evidence"):
        diagnosis_evidence = diagnosis_engine.build_diagnosis_evidence(
            normalized_symptoms=normalized_symptoms,
            raw_symptoms=symptoms,
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            fusion_probs=fusion_probs,
            fusion_meta=fusion_meta if isinstance(fusion_meta, dict) else {},
            modality_conflict_flag=modality_conflict_flag,
            final_disease=final_disease,
            final_confidence=final_confidence,
            final_source="fusion",
        )
    else:
        diagnosis_evidence = {
            "normalized_symptoms": normalized_symptoms,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "fusion_top3": fusion_top3,
            "weights": (fusion_meta.get("normalized_weights") if isinstance(fusion_meta, dict) else {}),
            "fusion_meta": fusion_meta,
            "modality_conflict_flag": modality_conflict_flag,
            "image_reliable": image_reliable,
            "text_reliable": text_reliable,
            "reliability_issue_types": reliability_issue_types,
            "supplement_mode": supplement_mode,
            "summary": f"融合诊断Top1: {final_disease}",
        }
    diagnosis_evidence["image_confusion_result"] = image_confusion_result
    diagnosis_evidence["text_confusion_result"] = text_confusion_result
    diagnosis_evidence["image_top3_adjusted"] = [(name, float(prob)) for name, prob in image_top3_adjusted]
    diagnosis_evidence["text_top3_adjusted"] = [(name, float(prob)) for name, prob in text_top3_adjusted]

    confidence_policy = make_confidence_flags(
        fusion_top3,
        fallback_confidence=float(final_confidence or 0.0),
        threshold=float(thresholds["diagnosis_conf_threshold"]),
        margin_threshold=float(thresholds["low_margin_threshold"]),
    )
    if confidence_policy.get("need_confirm"):
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", [])
        for reason in list(confidence_policy.get("reasons") or []):
            if reason not in flags["fallback_reason"]:
                flags["fallback_reason"].append(reason)

    # 使用纯函数评估确认决策（线上/离线共用逻辑）
    confirmation_result = evaluate_confirmation_decision(
        fusion_top3=fusion_top3,
        fusion_meta=fusion_meta if isinstance(fusion_meta, dict) else {},
        image_top3=image_top3,
        text_top3=text_top3,
        final_confidence=final_confidence,
        diagnosis_conf_threshold=float(thresholds["diagnosis_conf_threshold"]),
        low_margin_threshold=float(thresholds["low_margin_threshold"]),
    )
    
    # 统一回填纯函数结果，后面所有逻辑都用这一份
    fusion_case = str(confirmation_result["fusion_case"])
    weak_conflict_flag = bool(confirmation_result["weak_conflict_flag"])
    modality_conflict_flag = bool(confirmation_result["modality_conflict_flag"])
    image_reliable = bool(confirmation_result["image_reliable"])
    text_reliable = bool(confirmation_result["text_reliable"])
    supplement_mode = str(confirmation_result["supplement_mode"])
    
    # 先用 make_confidence_flags() 产出 low_confidence / low_margin
    # 再用 confirmation_result 叠加冲突类原因
    # 再根据 confirmation_result["should_clear_confirm"] 清理 low_confidence / low_margin
    if confirmation_result["need_confirm"]:
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", [])
        for reason in confirmation_result["reasons"]:
            if reason not in flags["fallback_reason"]:
                flags["fallback_reason"].append(reason)
    
    # 如果纯函数判断可以清除确认，则清除
    if confirmation_result["should_clear_confirm"]:
        flags["need_confirm"] = False
        reasons = [r for r in list(flags.get("fallback_reason") or []) if r != "low_margin"]
        reasons = [r for r in reasons if r != "low_confidence"]
        if reasons:
            flags["fallback_reason"] = reasons
        else:
            flags.pop("fallback_reason", None)

    disease_description = diagnosis_engine._get_disease_description(final_disease, normalized_symptoms)

    if personalization_context and final_disease:
        personalization_prompt = f"""以下是诊断结果，请结合农户个性化上下文给出补充提示：
诊断病害：{final_disease}
症状：{normalized_symptoms}
个性化上下文：{personalization_context}
原则：
1) 必须优先依据原始字段（location/weather/growth_stage/sowing_date/harvest_window_days）判断。
2) 风险标签仅作为辅助解释与约束提示，不能替代原始环境事实。
3) 若风险标签与原始字段冲突，以原始字段为准。
请输出1-2条与位置/设施/偏好有关的诊断风险提醒。"""
        try:
            extra_note = call_llm(
                personalization_prompt,
                "你是番茄病害诊断专家，善于根据农户个性化信息给出提醒。",
                temperature=0.4,
            )
            disease_description = (disease_description or "") + f"\n个性化提示：{extra_note.strip()}"
        except Exception:
            pass

    should_skip_low_conf_confirm = (
        fusion_case == "image_weak_text_strong"
        and text_reliable
        and final_confidence >= float(thresholds["diagnosis_conf_threshold"])
        and not weak_conflict_flag
    )
    if flags.get("confirm_when_low_confidence") and final_confidence < float(thresholds["diagnosis_conf_threshold"]) and not should_skip_low_conf_confirm:
        follow_ups = [
            "请补充叶片正反面近照。",
            "病斑颜色、边缘、是否有霉层或水渍状？",
            "近期是否高湿、连阴雨、棚内通风差？",
        ]
        follow_ups.extend(_build_follow_up_questions(normalized_symptoms, flags, state))
        if hard_constraints.get("forbid_professional_pesticides"):
            follow_ups = [
                "当前是否能购买合规药剂，还是仅能采用家庭可执行方案？",
                "现有喷雾设备条件如何（手动喷壶/背负式/弥雾/无人机）？",
            ] + follow_ups
        follow_ups = normalize_follow_up_questions(follow_ups)
        if follow_ups:
            state["diagnosis_follow_up_questions"] = follow_ups
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", [])
        if "low_confidence" not in flags["fallback_reason"]:
            flags["fallback_reason"].append("low_confidence")

    state["follow_up_questions"] = normalize_follow_up_questions(
        list(state.get("profile_follow_up_questions") or []) + list(state.get("diagnosis_follow_up_questions") or [])
    )
    flags["follow_up_questions"] = state["follow_up_questions"]

    message = f"番茄病害诊断智能体：诊断为{final_disease}，置信度={final_confidence:.2%}"
    if image_path and state.get("image_diagnosis"):
        message += f"\n图像诊断证据Top3: {state['image_diagnosis'].get('top3', [])}"
    if text_top3:
        message += f"\n文本诊断证据Top3: {[(d, round(p, 4)) for d, p in text_top3]}"
    if personalization_context:
        message += "（已参考个性化上下文）"

    state["final_disease"] = final_disease
    state["disease_type"] = final_disease
    state["disease_confidence"] = final_confidence
    state["image_confidence"] = image_confidence
    state["text_confidence"] = text_confidence
    state["final_confidence"] = final_confidence
    state["final_source"] = final_source
    state["fusion_mode"] = "gated_image_only" if (
        isinstance(fusion_meta, dict)
        and float(((fusion_meta.get("normalized_weights") or {}).get("image") or 0.0)) >= 0.999
        and float(((fusion_meta.get("normalized_weights") or {}).get("text") or 0.0)) <= 0.001
        and float(((fusion_meta.get("normalized_weights") or {}).get("prior") or 0.0)) <= 0.001
    ) else (
        "gated_text_only" if (
            isinstance(fusion_meta, dict)
            and float(((fusion_meta.get("normalized_weights") or {}).get("text") or 0.0)) >= 0.999
            and float(((fusion_meta.get("normalized_weights") or {}).get("image") or 0.0)) <= 0.001
            and float(((fusion_meta.get("normalized_weights") or {}).get("prior") or 0.0)) <= 0.001
        ) else "blended"
    )
    state["disease_description"] = disease_description
    state["image_probs"] = image_probs
    state["text_probs"] = text_probs
    state["prior_probs"] = prior_probs
    state["fusion_probs"] = fusion_probs
    state["text_top3"] = [(name, float(prob)) for name, prob in text_top3]
    state["fusion_top3"] = [(name, float(prob)) for name, prob in fusion_top3]
    state["diagnosis_evidence"] = diagnosis_evidence
    state["fusion_meta"] = fusion_meta if isinstance(fusion_meta, dict) else {}
    state["modality_conflict_flag"] = modality_conflict_flag
    state["image_reliable"] = image_reliable
    state["text_reliable"] = text_reliable
    state["reliability_issue_types"] = reliability_issue_types
    state["supplement_mode"] = supplement_mode
    state["weak_conflict_flag"] = weak_conflict_flag
    state["weak_conflict_candidate"] = weak_conflict_candidate
    state["debug_diagnosis"] = debug_payload
    state["personalization_flags"] = flags
    state["current_step"] = "diagnosis_complete"
    state["messages"] = [message]

    append_trace(
        state,
        agent="diagnosis",
        inputs={
            "crop_type": crop_type,
            "crop_growth_stage": crop_growth_stage,
            "symptoms": symptoms,
            "normalized_symptoms": normalized_symptoms,
            "image_path": image_path,
            "facility": facility,
            "province": province,
        },
        outputs={
            "disease_type": final_disease,
            "final_disease": final_disease,
            "disease_confidence": final_confidence,
            "image_confidence": image_confidence,
            "text_confidence": text_confidence,
            "final_confidence": final_confidence,
            "final_source": "fusion",
            "weights": (fusion_meta.get("normalized_weights") if isinstance(fusion_meta, dict) else {}),
            "fusion_meta": fusion_meta,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "fusion_top3": fusion_top3,
            "modality_conflict_flag": modality_conflict_flag,
            "image_reliable": image_reliable,
            "text_reliable": text_reliable,
            "reliability_issue_types": reliability_issue_types,
            "supplement_mode": supplement_mode,
            "weak_conflict_flag": weak_conflict_flag,
            "weak_conflict_candidate": weak_conflict_candidate,
            "diagnosis_evidence": diagnosis_evidence,
            "follow_up_questions": flags.get("follow_up_questions"),
            "need_confirm": flags.get("need_confirm"),
            "confirm_reasons": flags.get("fallback_reason"),
            "fallback_reason": flags.get("fallback_reason"),
            "fusion_mode": state.get("fusion_mode"),
            "model_id": model_meta["model_id"],
            "model_display_name": model_meta["model_display_name"],
            "backend": model_meta["backend"],
            "resolved_model_path": model_meta["resolved_model_path"],
            "model_fallback_reason": model_meta["model_fallback_reason"],
        },
    )
    return state

def _rule_based_diagnosis(crop_type: str, symptoms: list, priors: dict | None = None) -> tuple:
    """番茄病害规则匹配诊断（后备方案），可结合设施/区域先验。"""
    priors = priors or {}
    # 番茄病害知识库
    disease_knowledge = {
        "健康": {
            "symptoms": [],
            "confidence": 0.99,
            "description": "番茄植株生长正常，无病害症状。"
        },
        "早疫病": {
            "symptoms": ["斑点", "叶子发黄", "枯萎"],
            "confidence": 0.85,
            "description": "早疫病是番茄常见真菌性病害，在叶片上形成同心轮纹状病斑，边缘有黄色晕圈。"
        },
        "晚疫病": {
            "symptoms": ["斑点", "腐烂", "叶子发黄"],
            "confidence": 0.88,
            "description": "晚疫病会导致番茄果实和叶片快速腐烂，病斑呈水渍状，在潮湿环境下发展迅速。"
        },
        "黄化曲叶病毒病": {
            "symptoms": ["发黄", "卷曲", "生长缓慢"],
            "confidence": 0.92,
            "description": "由白粉虱传播的病毒病，导致叶片黄化、卷曲、变小，植株生长受阻。"
        },
        "叶霉病": {
            "symptoms": ["霉斑", "斑点", "叶子发黄"],
            "confidence": 0.83,
            "description": "叶霉病在叶片背面产生灰褐色霉层，正面出现黄色病斑，严重时叶片枯死。"
        },
        "细菌性斑点病": {
            "symptoms": ["斑点", "变色"],
            "confidence": 0.81,
            "description": "细菌性病害，在叶片和果实上形成小斑点，逐渐扩大并可能穿孔。"
        },
        "prevention_plan": _to_list(actions.get("prevention_plan") if isinstance(actions, dict) else []),
        "resistance_management": _to_list(actions.get("resistance_management") if isinstance(actions, dict) else []),
        "safety_notes": _to_list(actions.get("safety_notes") if isinstance(actions, dict) else []),
        "follow_up": _to_list(actions.get("follow_up") if isinstance(actions, dict) else []),
    }
def _build_llm_output_from_kb_snapshot(
    *,
    disease_type: str,
    kb_snapshot: dict,
    reason: str,
    policy_reasons: list[str],
    fallback_questions: list[str],
) -> TreatmentLLMOutput:
    actions = _normalize_kb_actions(kb_snapshot.get("actions") if isinstance(kb_snapshot, dict) else None)
    kb_treatment = str((kb_snapshot or {}).get("treatment") or "").strip()
    kb_prevention = str((kb_snapshot or {}).get("prevention") or "").strip()
    if not kb_treatment or not kb_prevention:
        fallback = kb_manager.get_treatment_plan(disease_type)
        kb_treatment = kb_treatment or str(fallback.get("treatment") or "咨询当地农技获取可执行替代方案。").strip()
        kb_prevention = kb_prevention or str(fallback.get("prevention") or "加强通风、控湿与清园。").strip()
        if not any(actions["treatment_plan"].values()):
            actions = _normalize_kb_actions(fallback.get("actions"))
    family = actions["treatment_plan"]["FAMILY"] or [kb_treatment or "咨询当地农技获取可执行替代方案。"]
    mid = actions["treatment_plan"]["MID"] or [kb_treatment or "咨询当地农技获取可执行替代方案。"]
    enterprise = actions["treatment_plan"]["ENTERPRISE"] or [kb_treatment or "咨询当地农技获取可执行替代方案。"]
    return TreatmentLLMOutput(
        overview=f"基于知识库的后备方案（原因：{reason}）",
        immediate_actions=actions["immediate_actions"] or ["先隔离疑似病株与重病叶，减少传播风险。"],
        treatment_plan=TreatmentPlanBranches(FAMILY=family, MID=mid, ENTERPRISE=enterprise),
        prevention_plan=actions["prevention_plan"] or [line for line in kb_prevention.splitlines() if line.strip()] or ["加强通风、控湿与清园。"],
        resistance_management=actions["resistance_management"] or ["不同作用机制药剂轮换，避免连续单一用药。"],
        safety_notes=actions["safety_notes"] or ["严格按标签与采收安全间隔执行。"],
        follow_up=actions["follow_up"] or ["48-72小时复查病斑扩展与叶面湿度情况。"],
        personalization_reasons=dedupe_reasons(policy_reasons),
        follow_up_questions=fallback_questions[:3],
    )
def treatment_agent(state: CropDiseaseState) -> CropDiseaseState:
    """
    番茄病害治疗方案智能体节点（使用大模型API）
    职责：
    1. 根据诊断结果制定番茄病害治疗方案
    2. 提供药物使用建议
    3. 给出预防措施
    Args:
        state: 当前系统状态
    Returns:
        更新后的状态
    """
    print("\n[番茄病害治疗方案智能体] 正在制定治疗方案...")
    disease_type = state.get("final_disease") or state.get("disease_type")
    crop_type = "番茄"
    crop_growth_stage = _canonicalize_growth_stage(state.get("crop_growth_stage"))
    symptoms = state.get("symptoms") or []
    disease_description = state.get("disease_description", "")
    profile, base_profile = _get_profile_from_state(state)
    constraints = profile.constraints if profile else TreatmentConstraint()
    flags = state.get("personalization_flags", {}) or {}
    policy = state.get("personalization_policy") or {}
    policy_reasons = dedupe_reasons(state.get("personalization_reasons") or flags.get("personalization_reasons") or [])
    hard_constraints = (policy.get("hard_constraints") or {}) if isinstance(policy, dict) else {}
    hard_constraints = hard_constraints if isinstance(hard_constraints, dict) else {}
    kb_snapshot = state.get("kb_snapshot") or {}
    base_info = {
        "facility": flags.get("facility") or (base_profile.facility if base_profile else None),
        "environment": flags.get("environment") or (base_profile.environment if base_profile else None),
        "growth_stage": _canonicalize_growth_stage(flags.get("growth_stage") or (base_profile.growth_stage if base_profile else None)),
        "province": flags.get("province") or (base_profile.province if base_profile else None),
    }
    must_forbid_professional = bool(hard_constraints.get("forbid_professional_pesticides"))
    forbidden_equipment_flows = [str(x) for x in (hard_constraints.get("forbidden_equipment_flows") or [])]
    banned_ingredients = [str(x) for x in (hard_constraints.get("banned_ingredients") or flags.get("banned_ingredients") or [])]
    harvest_window_days = hard_constraints.get("harvest_window_days")
    if harvest_window_days is None:
        harvest_window_days = flags.get("harvest_window_days")
    prefer_organic = bool(flags.get("prefer_organic") or constraints.prefer_organic)
    risk_items = [item for item in (flags.get("risk_items") or []) if item]
    risk_tags = [str(item).strip() for item in (flags.get("risk_tags") or []) if str(item).strip()]
    risk_context = {
        "risk_tags": risk_tags,
        "risk_items": [item.model_dump() if hasattr(item, "model_dump") else item for item in risk_items],
        "risk_summary": "、".join(risk_tags) if risk_tags else "暂无",
    }
    llm_output: TreatmentLLMOutput | None = None
    llm_failed_reason = ""
    def _build_prompt(branch: str, extra_requirements: str = "") -> str:
        return f"""你是番茄病害诊治系统治疗智能体。你要为番茄病害输出结构化处置方案，必须严格返回JSON，不要输出额外文字。
本次目标分叉 branch={branch}（由系统确定，禁止自行改动）。
{extra_requirements}
病害信息：
- 作物：{crop_type}
- 病害：{disease_type}
- 生育期：{crop_growth_stage or '未知'}
- 症状：{symptoms}
- 诊断说明：{disease_description}
知识证据（可参考但不可机械照抄，若提供 actions 模板需优先参考并结合个性化约束生成可执行步骤）：
{json.dumps(kb_snapshot, ensure_ascii=False)}
个性化策略（单一真源）：
{json.dumps(policy, ensure_ascii=False)}
基地信息：
{json.dumps(base_info, ensure_ascii=False)}
农业风险标签（辅助解释层，不可替代原始字段）：
{json.dumps(risk_context, ensure_ascii=False)}
事实优先规则：
- 必须优先使用原始字段（location/weather/growth_stage/sowing_date/harvest_window_days）。
- 风险标签只用于补充解释与强化提醒。
- 若冲突，以原始字段为准。
约束：
- banned_ingredients={banned_ingredients}
- harvest_window_days={harvest_window_days}
- prefer_organic={prefer_organic}
- forbid_professional_pesticides={must_forbid_professional}
- forbidden_equipment_flows={forbidden_equipment_flows}
强制规则：
1) FAMILY 不得出现无人机/规模化喷施/SOP/专业资质购药流程；若购药能力为NONE，避免要求购买专业药剂。
2) MID 可用背负式/常规可购药剂并强调安全间隔与轮换；仅当设备允许时可写无人机。
3) ENTERPRISE 可输出规模化SOP/监测/轮换，但仅设备包含DRONE时可写无人机流程。
4) 若 forbidden_equipment_flows 包含 DRONE，则全文不得出现无人机喷洒流程。
3) 不得推荐 banned_ingredients 中成分；可给“替代策略/咨询”。
4) harvest_window_days 较小（<=7）时，必须写采收窗口与安全间隔提醒。
5) 番茄场景必须强调通风、叶面干燥、修剪清园、监测复查。
输出JSON schema：
{{
  "overview": "...",
  "immediate_actions": ["..."],
  "treatment_plan": {{
     "FAMILY": ["..."],
     "MID": ["..."],
     "ENTERPRISE": ["..."]
  }},
  "prevention_plan": ["..."],
  "resistance_management": ["..."],
  "safety_notes": ["..."],
  "follow_up": ["..."],
  "personalization_reasons": ["...来自policy.explanations..."],
  "follow_up_questions": ["...最多3个..."]
}}"""
    selected_branch = _resolve_treatment_branch(flags)
    flags["selected_branch"] = selected_branch
    verification_result = state.get("verification_result") or {}
    rewrite_mode = bool(verification_result and verification_result.get("passed") is False)

    if rewrite_mode:
        system_prompt = TREATMENT_REWRITE_SYSTEM_PROMPT
        prompt = build_treatment_rewrite_prompt(
            disease_type=disease_type,
            crop_growth_stage=crop_growth_stage,
            symptoms=symptoms,
            disease_description=disease_description,
            kb_snapshot=kb_snapshot,
            policy=policy,
            flags=flags,
            old_treatment_plan=state.get("treatment_plan") or "",
            old_prevention_advice=state.get("prevention_advice") or "",
            verification_result=verification_result,
        )
    else:
        system_prompt = "你是番茄病害防治首席农艺师，输出必须专业、可执行、可审计，并严格遵守约束。"
        prompt = _build_prompt(selected_branch)
    for temperature in (0.4, 0.2):
        try:
            response = call_llm(prompt, system_prompt, temperature=temperature)
            parsed = extract_json_from_response(response)
            if not parsed:
                raise ValueError("JSON解析为空")
            llm_output = TreatmentLLMOutput.model_validate(parsed)
            break
        except (ValidationError, ValueError, Exception) as exc:
            llm_failed_reason = str(exc)
            llm_output = None
    if llm_output is None:
        flags["llm_failed"] = True
        flags["llm_failed_reason"] = llm_failed_reason[:200]
        llm_output = _build_llm_output_from_kb_snapshot(
            disease_type=disease_type,
            kb_snapshot=kb_snapshot,
            reason=llm_failed_reason[:80] or "模型输出不可解析",
            policy_reasons=policy_reasons,
            fallback_questions=normalize_follow_up_questions(flags.get("follow_up_questions") or []),
        )
    else:
        flags["llm_failed"] = False
    branch_lines = getattr(llm_output.treatment_plan, selected_branch)
    treatment_text = "\n".join([
        f"【方案概述】{llm_output.overview}",
        "【立即行动】" + "；".join(llm_output.immediate_actions),
        f"【差异化处置-{selected_branch}】" + "；".join(branch_lines),
        "【抗性管理】" + "；".join(llm_output.resistance_management),
        "【安全注意】" + "；".join(llm_output.safety_notes),
        "【复查计划】" + "；".join(llm_output.follow_up),
    ]).strip()
    prevention_advice = "\n".join(llm_output.prevention_plan).strip()
    violations = _validate_treatment_output(
        branch=selected_branch,
        hard_constraints=hard_constraints,
        flags=flags,
        constraints=constraints,
        treatment_text=treatment_text,
        prevention_text=prevention_advice,
    )
    if violations:
        retry_prompt = _build_prompt(selected_branch, extra_requirements="以下约束被违反，请修正后输出JSON：" + "；".join(violations))
        try:
            retry_response = call_llm(retry_prompt, system_prompt, temperature=0.1)
            retry_parsed = extract_json_from_response(retry_response)
            if retry_parsed:
                llm_output = TreatmentLLMOutput.model_validate(retry_parsed)
                branch_lines = getattr(llm_output.treatment_plan, selected_branch)
                treatment_text = "\n".join([
                    f"【方案概述】{llm_output.overview}",
                    "【立即行动】" + "；".join(llm_output.immediate_actions),
                    f"【差异化处置-{selected_branch}】" + "；".join(branch_lines),
                    "【抗性管理】" + "；".join(llm_output.resistance_management),
                    "【安全注意】" + "；".join(llm_output.safety_notes),
                    "【复查计划】" + "；".join(llm_output.follow_up),
                ]).strip()
                prevention_advice = "\n".join(llm_output.prevention_plan).strip()
                violations = _validate_treatment_output(
                    branch=selected_branch,
                    hard_constraints=hard_constraints,
                    flags=flags,
                    constraints=constraints,
                    treatment_text=treatment_text,
                    prevention_text=prevention_advice,
                )
        except Exception:
            pass
    if violations:
        flags["llm_failed"] = True
        flags["llm_failed_reason"] = "constraint_violation"
        kb_fallback_output = _build_llm_output_from_kb_snapshot(
            disease_type=disease_type,
            kb_snapshot=kb_snapshot,
            reason="constraint_violation",
            policy_reasons=policy_reasons,
            fallback_questions=normalize_follow_up_questions(flags.get("follow_up_questions") or []),
        )
        fallback_branch_lines = getattr(kb_fallback_output.treatment_plan, selected_branch)
        treatment_text = "\n".join([
            f"【方案概述】{kb_fallback_output.overview}",
            "【立即行动】" + "；".join(kb_fallback_output.immediate_actions),
            f"【差异化处置-{selected_branch}】" + "；".join(fallback_branch_lines),
            "【抗性管理】" + "；".join(kb_fallback_output.resistance_management),
            "【安全注意】" + "；".join(kb_fallback_output.safety_notes),
            "【复查计划】" + "；".join(kb_fallback_output.follow_up),
        ]).strip()
        prevention_advice = "\n".join(kb_fallback_output.prevention_plan).strip()
    treatment_text, prevention_advice = _apply_branch_post_fixes(
        selected_branch,
        hard_constraints,
        flags,
        treatment_text,
        prevention_advice,
    )
    personalized_plan, personalized_prevention, personalization_outputs = apply_personalization_to_treatment(
        treatment_text,
        prevention_advice,
        flags,
    )
    treatment_plan = personalized_plan or treatment_text
    prevention_advice = personalized_prevention or prevention_advice
    flags.update(personalization_outputs)
    kb_ingredients = [str(item).strip() for item in (kb_snapshot.get("ingredients") or []) if str(item).strip()]
    banned_set = {str(x).strip().lower() for x in (hard_constraints.get("banned_ingredients") or flags.get("banned_ingredients") or []) if str(x).strip()}
    ingredient_hits = sorted({item for item in kb_ingredients if item.lower() in banned_set})
    if ingredient_hits and flags.get("filtered"):
        flags["filtered_components"] = sorted(set([*(flags.get("filtered_components") or []), *ingredient_hits]))
    flags.update(normalize_filter_outputs(flags))
    if llm_output.personalization_reasons:
        flags["personalization_reasons"] = dedupe_reasons(list(llm_output.personalization_reasons) + policy_reasons)
    elif policy_reasons:
        flags["personalization_reasons"] = dedupe_reasons(policy_reasons)
    if llm_output.follow_up_questions:
        flags["post_treatment_questions"] = dedupe_reasons(llm_output.follow_up_questions)[:3]
    flags["follow_up_questions"] = normalize_follow_up_questions(flags.get("follow_up_questions") or [])
    state["follow_up_questions"] = flags["follow_up_questions"]
    flags["personalization_applied"] = compute_personalization_applied(state, flags)
    state["personalization_flags"] = flags
    message = f"番茄病害治疗方案智能体：已生针对{disease_type}的治疗方案"
    # 更新状态
    state["treatment_plan"] = treatment_plan
    state["prevention_advice"] = prevention_advice
    if rewrite_mode:
        # 重写完成后清空旧审查结果，确保 supervisor 进入新的 verification 节点复审
        state["verification_result"] = None
        state["verification_passed"] = None
        state["verification_risk_level"] = None
        state["verification_issues"] = []
        state["verification_must_fix"] = []
        state["verification_summary"] = None
    state["current_step"] = "treatment_complete"
    state["messages"] = [message]
    print(f"  - 治疗方案: {treatment_plan[:50]}...")
    print(f"  - 预防建议: {prevention_advice[:50]}...")
    append_trace(
        state,
        agent="treatment",
        inputs={
            "disease_type": disease_type,
            "crop_growth_stage": crop_growth_stage,
            "kb_snapshot": state.get("kb_snapshot"),
        },
        outputs={
            "treatment_plan": treatment_plan,
            "prevention_advice": prevention_advice,
            "selected_branch": selected_branch,
            "llm_failed": flags.get("llm_failed"),
            "personalization_reasons": dedupe_reasons(flags.get("personalization_reasons") or []),
            "personalization_applied": flags.get("personalization_applied", False),
            "filtered": flags.get("filtered", False),
            "filtered_reasons": flags.get("filtered_reasons") or [],
            "filtered_components": flags.get("filtered_components") or [],
            "filtered_actions": flags.get("filtered_actions") or [],
            "risk_tags": [str(item) for item in (flags.get("risk_tags") or [])],
            "risk_summary": "、".join([str(item).strip() for item in (flags.get("risk_tags") or []) if str(item).strip()]) or "",
        },
    )
    return state
def _get_treatment_from_knowledge_base(disease_type: str) -> tuple:
    """番茄病害知识库（后备方案）"""
    # 使用知识库管理器获取治疗方案
    treatment_plan = kb_manager.get_treatment_plan(disease_type)
    return treatment_plan["treatment"], treatment_plan["prevention"]
def _get_profile_from_state(state: CropDiseaseState) -> tuple[Optional[FarmerProfile], Optional[BaseProfile]]:
    """从状态中解析档案对象及基地。"""
    profile_data = state.get("farmer_profile")
    if not profile_data:
        return None, None
    try:
        profile = FarmerProfile.model_validate(profile_data)
    except Exception:
        return None, None
    base_id = state.get("base_id") or profile.active_base_id
    base_profile = None
    if base_id and base_id in profile.bases:
        base_profile = profile.bases[base_id]
    return profile, base_profile
def _fill_missing_from_profile(state: CropDiseaseState, base_profile: Optional[BaseProfile]) -> None:
    """使用基地信息补全缺失字段。"""
    if not base_profile:
        return
    if not state.get("location") and base_profile.location:
        state["location"] = base_profile.location
    if not state.get("province") and base_profile.province:
        state["province"] = base_profile.province
    if not state.get("facility") and base_profile.facility:
        state["facility"] = base_profile.facility
    if not state.get("environment") and base_profile.environment:
        state["environment"] = base_profile.environment
    if not state.get("crop_growth_stage") and base_profile.growth_stage:
        state["crop_growth_stage"] = _canonicalize_growth_stage(base_profile.growth_stage)
REQUIRED_PROFILE_FIELDS = ["farm_scale", "pesticide_access_level", "prefer_organic", "harvest_window_days"]
OPTIONAL_PROFILE_FIELDS = ["equipment", "growth_stage", "experience_level", "cultivation_mode", "risk_preference", "environment"]


def _find_missing_profile_fields(
    profile: Optional[FarmerProfile],
    base_profile: Optional[BaseProfile],
    policy: Optional[dict] = None,
) -> list[str]:
    """检查档案中缺少字段，缺失仅提示追问，不阻断番茄治疗方案生成。"""
    if not profile:
        return ["farm_scale", "pesticide_access_level", "prefer_organic", "base_id", "location", "growth_stage"]
    missing = []
    for field in ["farm_scale", "pesticide_access_level", "cultivation_mode", "experience_level", "risk_preference"]:
        if not getattr(profile, field, None):
            missing.append(field)
    constraints = getattr(profile, "constraints", None)
    if constraints is None or getattr(constraints, "prefer_organic", None) is None:
        missing.append("prefer_organic")
    if constraints is None or getattr(constraints, "harvest_window_days", None) is None:
        missing.append("harvest_window_days")
    scale = getattr(profile, "farm_scale", None)
    equipment = list(getattr(profile, "equipment", []) or [])
    if scale in {"GREENHOUSE_LARGE", "LARGE"} and not equipment:
        missing.append("equipment")
    if base_profile is None:
        missing.extend(["base_id", "location", "growth_stage"])
    else:
        if not base_profile.location:
            missing.append("location")
        if not base_profile.growth_stage:
            missing.append("growth_stage")
        if not base_profile.environment:
            missing.append("environment")
    return list(dict.fromkeys(missing))




def _normalize_kb_actions(actions: dict | None) -> dict:
    """兼容 actions 结构，避免缺字段导致下游报错。"""
    default = {
        "immediate_actions": [],
        "treatment_plan": {"FAMILY": [], "MID": [], "ENTERPRISE": []},
        "prevention_plan": [],
        "resistance_management": [],
        "safety_notes": [],
        "follow_up": [],
    }
    if not isinstance(actions, dict):
        return default
    merged = dict(default)
    merged.update({k: v for k, v in actions.items() if k in merged})
    tp = merged.get("treatment_plan") if isinstance(merged.get("treatment_plan"), dict) else {}
    merged["treatment_plan"] = {
        "FAMILY": list(tp.get("FAMILY") or []),
        "MID": list(tp.get("MID") or []),
        "ENTERPRISE": list(tp.get("ENTERPRISE") or []),
    }
    for key in ["immediate_actions", "prevention_plan", "resistance_management", "safety_notes", "follow_up"]:
        merged[key] = list(merged.get(key) or [])
    return merged



def _resolve_treatment_branch(flags: dict | None) -> str:
    """根据档案规模选择治疗分支。"""
    flags = flags or {}
    scale = str(flags.get("farm_scale") or "").upper()
    if scale in {"BALCONY", "SMALL"}:
        return "FAMILY"
    if scale in {"LARGE", "GREENHOUSE_LARGE"}:
        return "ENTERPRISE"
    return "MID"

def _resolve_confirm_ui_mode(flags: dict, state: CropDiseaseState) -> str:
    mode = str(flags.get("confirm_ui_mode") or state.get("confirm_ui_mode") or "").strip()
    if mode in {"image", "text", "image_and_text"}:
        return mode
    supplement_mode = str(state.get("supplement_mode") or flags.get("supplement_mode") or "").strip()
    if supplement_mode == "image_only":
        return "image"
    if supplement_mode == "text_only":
        return "text"
    if supplement_mode == "image_and_text":
        return "image_and_text"
    return "image_and_text"


def _extract_weak_evidence_types(flags: dict, state: CropDiseaseState, ui_mode: str) -> list[str]:
    types: list[str] = []
    fallback_reason = list(flags.get("fallback_reason") or [])
    reliability_issues = list(state.get("reliability_issue_types") or flags.get("reliability_issue_types") or [])
    fusion_case = str(state.get("fusion_case") or "").strip()
    image_reliable = bool(state.get("image_reliable"))
    text_reliable = bool(state.get("text_reliable"))

    if not image_reliable:
        types.append("image_weak")
    if not text_reliable:
        types.append("text_weak")
    if "weak_image_text_conflict" in reliability_issues or "image_text_conflict" in fallback_reason or "conflict" in fusion_case:
        types.append("weak_image_text_conflict")
    if "low_margin" in fallback_reason:
        types.append("low_margin")
    if not image_reliable and not text_reliable:
        types.append("both_weak")
    if "low_confidence" in fallback_reason and "both_weak" not in types and not types:
        types.append("both_weak")

    if not types:
        if ui_mode == "image":
            types.append("image_weak")
        elif ui_mode == "text":
            types.append("text_weak")
        else:
            types.append("both_weak")
    return list(dict.fromkeys(types))


def _identify_confusion_groups(symptoms: list[str], flags: dict, state: CropDiseaseState) -> list[str]:
    symptom_text = " ".join(str(s) for s in (symptoms or [])).lower()
    top_candidates = [name for name, _ in list(state.get("fusion_top3") or [])[:3]]
    fallback_reason = " ".join(str(r) for r in (flags.get("fallback_reason") or [])).lower()
    fusion_case = str(state.get("fusion_case") or "").lower()
    discriminator_groups = list(state.get("symptom_discriminator_groups") or [])
    discriminator_text = " ".join(str(item) for item in discriminator_groups).lower()
    candidate_text = " ".join(str(name) for name in top_candidates)

    groups: list[str] = []
    spot_group = {"细菌性斑点病", "早疫病", "晚疫病", "叶霉病", "叶斑病", "靶斑病"}
    virus_group = {"黄化曲叶病毒病", "花叶病毒病"}
    mite_group = {"蜘蛛螨", "细菌性斑点病", "早疫病", "叶斑病", "靶斑病"}

    virus_signal = any(name in candidate_text for name in virus_group) or any(k in symptom_text for k in ["卷叶", "花叶", "黄化", "畸形"]) or "virus" in discriminator_text
    spot_signal = any(name in candidate_text for name in spot_group) or any(k in symptom_text for k in ["斑", "轮纹", "靶斑", "霉层"]) or "spot" in discriminator_text
    if virus_signal:
        groups.append("病毒组")
    if spot_signal and not (virus_signal and any(k in symptom_text for k in ["卷叶", "花叶", "黄化", "畸形"])):
        groups.append("斑点叶斑组")
    if any(name in candidate_text for name in mite_group) and ("蜘蛛螨" in candidate_text or any(k in symptom_text for k in ["叶背", "细网", "虫点", "青铜"])):
        groups.append("蜘蛛螨混淆组")
    if "conflict" in fallback_reason or "conflict" in fusion_case:
        if "蜘蛛螨" in candidate_text and "蜘蛛螨混淆组" not in groups:
            groups.append("蜘蛛螨混淆组")

    return list(dict.fromkeys(groups))


def build_follow_up_context(symptoms: list[str], flags: dict, state: CropDiseaseState) -> dict[str, Any]:
    ui_mode = _resolve_confirm_ui_mode(flags, state)
    weak_evidence_types = _extract_weak_evidence_types(flags, state, ui_mode)
    confusion_groups = _identify_confusion_groups(symptoms, flags, state)
    has_discriminative_text_evidence = bool(state.get("symptom_discriminator_groups") or state.get("text_top3"))
    return {
        "ui_mode": ui_mode,
        "weak_evidence_types": weak_evidence_types,
        "confusion_groups": confusion_groups,
        "has_discriminative_text_evidence": has_discriminative_text_evidence,
    }


def _build_follow_up_questions(symptoms: list[str], flags: dict, state: CropDiseaseState) -> list[str]:
    context = build_follow_up_context(symptoms, flags, state)
    ui_mode = context["ui_mode"]
    weak_types = context["weak_evidence_types"]
    confusion_groups = context["confusion_groups"]

    image_questions = list(FOLLOW_UP_RULES["ui_mode_templates"]["image"])
    text_questions = list(FOLLOW_UP_RULES["ui_mode_templates"]["text"])
    dual_questions = list(FOLLOW_UP_RULES["ui_mode_templates"]["image_and_text"])

    if ui_mode == "image":
        selected: list[str] = image_questions[:3]
    elif ui_mode == "text":
        selected = text_questions[:3]
    else:
        selected = [image_questions[0], image_questions[1], text_questions[0], text_questions[1]]

    if "image_weak" in weak_types and ui_mode != "text":
        selected = image_questions[:3] + selected
    if "text_weak" in weak_types and ui_mode != "image":
        selected = text_questions[:3] + selected
    if "both_weak" in weak_types and ui_mode == "image_and_text":
        selected = [image_questions[0], image_questions[1], text_questions[0], text_questions[1]] + dual_questions
    if "weak_image_text_conflict" in weak_types:
        if ui_mode == "image":
            selected = image_questions[:3] + selected
        elif ui_mode == "text":
            selected = text_questions[:3] + selected
        else:
            selected = [image_questions[0], text_questions[0]] + selected

    if confusion_groups:
        prioritized_group_questions: list[str] = []
        for group_name in confusion_groups:
            group_items = FOLLOW_UP_RULES["confusion_group_questions"].get(group_name, [])
            if ui_mode == "image":
                prioritized_group_questions.extend(group_items[:1])
            elif "low_margin" in weak_types or "text_weak" in weak_types:
                prioritized_group_questions.extend(group_items[:3])
            else:
                prioritized_group_questions.extend(group_items[:2])
        if ui_mode == "image":
            selected = selected + prioritized_group_questions
        else:
            selected = prioritized_group_questions + selected

    selected = [item for item in selected if item]
    return normalize_follow_up_questions(selected)[:4]

def _build_profile_follow_up_questions(
    missing_fields: list[str],
    profile: Optional[FarmerProfile],
    base_profile: Optional[BaseProfile],
    policy: Optional[dict] = None,
) -> list[str]:
    """根据档案缺失项生成追问问句（仅用于待补充信息，不混入解释性 reasons）。"""
    _ = (profile, base_profile, policy)
    return build_missing_field_questions(missing_fields)[:3]





def _apply_branch_post_fixes(
    branch: str,
    hard_constraints: dict | None,
    flags: dict | None,
    treatment_text: str,
    prevention_text: str,
) -> tuple[str, str]:
    """分支后处理（兼容实现，不改变既有文本）。"""
    _ = (branch, hard_constraints, flags)
    return treatment_text, prevention_text


def build_verification_prompt(payload: dict) -> str:
    return f"""
请对下面的番茄病害治疗方案进行农业合规性审查。

【诊断结果】
- 作物：{payload.get("crop_type")}
- 病害：{payload.get("final_disease")}
- 置信度：{payload.get("final_confidence")}
- 症状：{payload.get("symptoms")}
- 生长阶段：{payload.get("crop_growth_stage")}

【农户档案约束】
- 农场规模：{payload.get("farm_scale")}
- 购药能力：{payload.get("pesticide_access_level")}
- 设备：{payload.get("equipment")}
- 栽培模式：{payload.get("cultivation_mode")}
- 风险偏好：{payload.get("risk_preference")}
- 偏好有机：{payload.get("prefer_organic")}
- 采收窗口天数：{payload.get("harvest_window_days")}
- 禁用成分：{payload.get("banned_ingredients")}
- 分档：{payload.get("selected_branch")}

【基地与环境】
- 基地位置：{payload.get("location")}
- 设施类型：{payload.get("facility")}
- 环境描述：{payload.get("environment")}
- 天气摘要：{payload.get("weather_summary")}
- 湿度：{payload.get("humidity")}
- 降雨概率：{payload.get("precipitation_probability")}
- 风险标签：{payload.get("risk_tags")}

【知识库证据】
{json.dumps(payload.get("kb_snapshot") or {}, ensure_ascii=False)}

【待审查治疗方案】
{payload.get("treatment_plan")}

【待审查预防建议】
{payload.get("prevention_advice")}

请严格输出 JSON：
{{
  "passed": true,
  "risk_level": "low|medium|high",
  "issues": ["..."],
  "must_fix": ["..."],
  "suggested_rewrite_points": ["..."],
  "compliance_summary": "..."
}}
"""


def build_treatment_rewrite_prompt(
    *,
    disease_type: str,
    crop_growth_stage: str | None,
    symptoms: list[str],
    disease_description: str,
    kb_snapshot: dict,
    policy: dict,
    flags: dict,
    old_treatment_plan: str,
    old_prevention_advice: str,
    verification_result: dict,
) -> str:
    return f"""
请根据未通过的农业合规审查意见，重写番茄病害处置方案。

【病害信息】
- 病害：{disease_type}
- 生长阶段：{crop_growth_stage or "未知"}
- 症状：{symptoms}
- 诊断说明：{disease_description}

【知识库证据】
{json.dumps(kb_snapshot, ensure_ascii=False)}

【个性化策略】
{json.dumps(policy or {}, ensure_ascii=False)}

【档案约束】
{json.dumps(flags or {}, ensure_ascii=False)}

【原治疗方案】
{old_treatment_plan}

【原预防建议】
{old_prevention_advice}

【审查问题】
{verification_result.get("issues") or []}

【必须修正】
{verification_result.get("must_fix") or []}

【建议改写方向】
{verification_result.get("suggested_rewrite_points") or []}

输出 JSON schema：
{{
  "overview": "...",
  "immediate_actions": ["..."],
  "treatment_plan": {{
    "FAMILY": ["..."],
    "MID": ["..."],
    "ENTERPRISE": ["..."]
  }},
  "prevention_plan": ["..."],
  "resistance_management": ["..."],
  "safety_notes": ["..."],
  "follow_up": ["..."],
  "personalization_reasons": ["..."],
  "follow_up_questions": ["..."]
}}
"""


def _normalize_verification_result(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {
            "passed": False,
            "risk_level": "high",
            "issues": ["verification_parse_error"],
            "must_fix": ["请重新生成可审查的方案"],
            "suggested_rewrite_points": [],
            "compliance_summary": "审查结果解析失败，不能直接下发方案。",
        }

    return {
        "passed": bool(result.get("passed")),
        "risk_level": str(result.get("risk_level") or "high"),
        "issues": [str(x) for x in (result.get("issues") or [])],
        "must_fix": [str(x) for x in (result.get("must_fix") or [])],
        "suggested_rewrite_points": [str(x) for x in (result.get("suggested_rewrite_points") or [])],
        "compliance_summary": str(result.get("compliance_summary") or ""),
    }


def _rule_based_verification(payload: dict) -> list[str]:
    issues: list[str] = []

    treatment_text = str(payload.get("treatment_plan") or "")
    prevention_text = str(payload.get("prevention_advice") or "")
    full_text = "\n".join([treatment_text, prevention_text])

    banned_ingredients = [str(x).strip() for x in (payload.get("banned_ingredients") or []) if str(x).strip()]
    for ingredient in banned_ingredients:
        if ingredient and ingredient in full_text:
            issues.append(f"方案包含禁用成分：{ingredient}")

    selected_branch = str(payload.get("selected_branch") or "").upper()
    if selected_branch == "FAMILY":
        for term in ["无人机", "规模化喷施", "SOP", "专业资质购药流程"]:
            if term in full_text:
                issues.append(f"家庭级方案不应包含：{term}")

    harvest_window_days = payload.get("harvest_window_days")
    try:
        harvest_window_days = int(harvest_window_days) if harvest_window_days is not None else None
    except Exception:
        harvest_window_days = None

    if harvest_window_days is not None and harvest_window_days <= 7:
        if "安全间隔" not in full_text and "采收" not in full_text:
            issues.append("采收窗口较短，但方案未明确提示安全间隔或采收注意事项")

    humidity = payload.get("humidity")
    try:
        humidity = float(humidity) if humidity is not None else None
    except Exception:
        humidity = None

    disease = str(payload.get("final_disease") or "")
    if disease == "晚疫病" and humidity is not None and humidity >= 90:
        if "高湿" not in full_text and "风险" not in full_text and "立即" not in full_text:
            issues.append("晚疫病且湿度过高，但方案缺少病情爆发风险警示")

    return dedupe_reasons(issues)


def _extract_weather_numbers(summary: str | None) -> tuple[float | None, float | None, float | None, float | None]:
    text = str(summary or "")
    if not text:
        return None, None, None, None
    humidity = None
    precipitation_probability = None
    temperature = None
    wind_speed = None
    humidity_match = re.search(r"湿度\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", text)
    rain_match = re.search(r"(降雨概率|降水概率)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*%", text)
    temp_match = re.search(r"(气温|温度)\s*[:：]?\s*(-?\d+(?:\.\d+)?)\s*[℃cC]", text)
    wind_match = re.search(r"(风速)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(m/s|米/秒)?", text)
    if humidity_match:
        try:
            humidity = float(humidity_match.group(1))
        except Exception:
            humidity = None
    if rain_match:
        try:
            precipitation_probability = float(rain_match.group(2))
        except Exception:
            precipitation_probability = None
    if temp_match:
        try:
            temperature = float(temp_match.group(2))
        except Exception:
            temperature = None
    if wind_match:
        try:
            wind_speed = float(wind_match.group(2))
        except Exception:
            wind_speed = None
    return humidity, precipitation_probability, temperature, wind_speed

def _validate_treatment_output(
    *,
    branch: str,
    hard_constraints: dict | None,
    flags: dict | None,
    treatment_text: str,
    prevention_text: str,
    constraints: TreatmentConstraint | None = None,
) -> list[str]:
    """约束校验：命中违规时触发 LLM retry/fallback。"""
    hard_constraints = hard_constraints or {}
    flags = flags or {}

    full_text = "\n".join([str(treatment_text or ""), str(prevention_text or "")])
    violations: list[str] = []

    # 禁用成分来源：profile constraints + hard_constraints + flags
    banned_ingredients = sorted({
        *[str(item).strip() for item in ((constraints.banned_ingredients if constraints else None) or []) if str(item).strip()],
        *[str(item).strip() for item in (hard_constraints.get("banned_ingredients") or []) if str(item).strip()],
        *[str(item).strip() for item in (flags.get("banned_ingredients") or []) if str(item).strip()],
    })
    for ingredient in banned_ingredients:
        if ingredient and ingredient in full_text:
            violations.append(f"包含禁用成分：{ingredient}")

    # 家庭分支不应出现专业化大规模流程
    if str(branch or "").upper() == "FAMILY":
        forbidden_terms = ["无人机", "规模化喷施", "SOP", "专业资质购药流程"]
        for term in forbidden_terms:
            if term in full_text:
                violations.append(f"FAMILY 分支不得包含：{term}")

    # 设备禁用流转约束
    forbidden_equipment_flows = [str(item).strip().upper() for item in (hard_constraints.get("forbidden_equipment_flows") or []) if str(item).strip()]
    if "DRONE" in forbidden_equipment_flows and "无人机" in full_text:
        violations.append("当前档案禁止无人机流程")

    # 去重并保序
    return dedupe_reasons(violations)

def _summarize_constraints(constraints: TreatmentConstraint) -> str:
    """将治疗约束转为简短文本。"""
    parts = []
    if constraints.banned_ingredients:
        parts.append(f"禁用成分：{', '.join(constraints.banned_ingredients)}")
    if constraints.prefer_organic:
        parts.append("偏好有机/低残留")
    if constraints.harvest_window_days:
        parts.append(f"采收临近：约{constraints.harvest_window_days}天")
    return "；".join(parts) if parts else "无"


def verification_agent(state: CropDiseaseState) -> CropDiseaseState:
    print("\n[农业合规审查智能体] 正在审查治疗方案...")

    flags = state.get("personalization_flags", {}) or {}
    profile, base_profile = _get_profile_from_state(state)
    _ = (profile, base_profile)
    weather_summary = state.get("weather_summary") or state.get("environment")
    humidity = state.get("humidity")
    precipitation_probability = state.get("precipitation_probability")
    parsed_humidity, parsed_precip, parsed_temperature, parsed_wind_speed = _extract_weather_numbers(
        str(weather_summary) if weather_summary is not None else None
    )
    if humidity is None:
        humidity = parsed_humidity
    if precipitation_probability is None:
        precipitation_probability = parsed_precip

    payload = {
        "crop_type": state.get("crop_type", "番茄"),
        "final_disease": state.get("final_disease") or state.get("disease_type"),
        "final_confidence": state.get("final_confidence"),
        "symptoms": state.get("symptoms") or [],
        "crop_growth_stage": state.get("crop_growth_stage"),
        "farm_scale": flags.get("farm_scale"),
        "pesticide_access_level": flags.get("pesticide_access_level"),
        "equipment": flags.get("equipment") or [],
        "cultivation_mode": flags.get("cultivation_mode"),
        "risk_preference": flags.get("risk_preference"),
        "prefer_organic": flags.get("prefer_organic"),
        "harvest_window_days": flags.get("harvest_window_days"),
        "banned_ingredients": flags.get("banned_ingredients") or [],
        "selected_branch": flags.get("selected_branch"),
        "location": state.get("location"),
        "facility": state.get("facility"),
        "environment": state.get("environment"),
        "weather_summary": weather_summary,
        "humidity": humidity,
        "precipitation_probability": precipitation_probability,
        "temperature": parsed_temperature,
        "wind_speed": parsed_wind_speed,
        "risk_tags": flags.get("risk_tags") or [],
        "kb_snapshot": state.get("kb_snapshot") or {},
        "treatment_plan": state.get("treatment_plan") or "",
        "prevention_advice": state.get("prevention_advice") or "",
    }

    rule_issues = _rule_based_verification(payload)

    llm_enabled = bool(get_admin_flag("llm.enable_llm", True))
    llm_result = None
    if llm_enabled:
        try:
            prompt = build_verification_prompt(payload)
            response = call_llm(prompt, VERIFICATION_SYSTEM_PROMPT, temperature=0.1)
            llm_result = extract_json_from_response(response)
        except Exception as exc:
            llm_result = {
                "passed": False,
                "risk_level": "high",
                "issues": [f"verification_llm_error: {str(exc)}"],
                "must_fix": ["请重新审查并重写方案"],
                "suggested_rewrite_points": [],
                "compliance_summary": "审查过程异常，不能直接下发方案。",
            }
    else:
        llm_result = {
            "passed": True,
            "risk_level": "low",
            "issues": [],
            "must_fix": [],
            "suggested_rewrite_points": [],
            "compliance_summary": "LLM 已关闭，当前仅执行规则审查。",
        }

    review_result = _normalize_verification_result(llm_result)

    if rule_issues:
        review_result["passed"] = False
        review_result["risk_level"] = "high"
        review_result["issues"] = dedupe_reasons(rule_issues + review_result["issues"])
        review_result["must_fix"] = dedupe_reasons(
            review_result["must_fix"] + [
                "移除禁用成分或违规流程",
                "补充与分档、设备能力、采收安全间隔一致的说明",
            ]
        )
        if not review_result["compliance_summary"]:
            review_result["compliance_summary"] = "规则审查发现明显农业合规风险。"

    state["verification_result"] = review_result
    state["verification_passed"] = bool(review_result.get("passed"))
    state["verification_risk_level"] = str(review_result.get("risk_level") or "high")
    state["verification_issues"] = list(review_result.get("issues") or [])
    state["verification_must_fix"] = list(review_result.get("must_fix") or [])
    state["verification_summary"] = str(review_result.get("compliance_summary") or "")
    state["current_step"] = "verification_complete"
    state["messages"] = [
        f"农业合规审查智能体：审查{'通过' if state['verification_passed'] else '未通过'}，风险等级={state['verification_risk_level']}"
    ]

    append_trace(
        state,
        agent="verification",
        inputs=payload,
        outputs=review_result,
        decision={
            "next_action": "end" if state["verification_passed"] else "treatment",
            "reason": state["verification_summary"],
            "reasons": state["verification_issues"],
        },
    )

    return state


def _deterministic_supervisor_decision(state: CropDiseaseState, flags: dict, missing_profile_fields: list[str]) -> tuple[str, bool, str, list[str]]:
    """确定性路由，增加 verification 闭环。"""
    requested_action = str(state.get("next_action") or "").strip()
    current_step = str(state.get("current_step") or "")
    if current_step == "start" and requested_action == "reception":
        return "reception", False, "番茄病害监督智能体：初诊起始阶段，先进入接待智能体", ["initial_reception_entry"]
    if requested_action in {"confirm_input", "confirm_choice"}:
        return requested_action, False, f"番茄病害监督智能体：按状态恢复请求继续执行 {requested_action}", ["resume_requested_action"]

    has_diagnosis = bool(state.get("final_disease") or state.get("disease_type"))
    has_confidence = (_safe_float(state.get("final_confidence")) or _safe_float(state.get("disease_confidence")) or 0.0) > 0
    if not has_diagnosis:
        return "diagnosis", False, "番茄病害监督智能体：缺少诊断结果，先执行诊断智能体", ["missing_diagnosis"]
    if not has_confidence and str(state.get("confirmation_mode") or "") != "confirm_choice":
        return "diagnosis", False, "番茄病害监督智能体：置信度不足，先执行诊断智能体", ["missing_confidence"]

    if flags.get("need_confirm"):
        confirm_round_index = int(state.get("confirm_round_index") or 0)
        raw_confirm_round_limit = get_admin_flag("workflow.confirm_round_limit", 1)
        confirm_round_limit = int(1 if raw_confirm_round_limit is None else raw_confirm_round_limit)
        if confirm_round_index >= confirm_round_limit:
            return "manual_review", True, "番茄病害监督智能体：补充诊断后仍不确定，建议结束当前图并由用户决定是否转入专家复核", ["need_confirm_manual_review"]
        return "await_user_confirmation", True, "番茄病害监督智能体：需用户进入补充诊断，当前轮结束并返回追问问题", ["need_confirm_wait_user"]

    if not state.get("kb_snapshot"):
        return "kb_retrieval", False, "番茄病害监督智能体：缺少知识快照，进入知识检索智能体", ["missing_kb_snapshot"]

    llm_enabled = bool(get_admin_flag("llm.enable_llm", True))
    enable_treatment_generation = llm_enabled and bool(get_admin_flag("llm.enable_treatment_generation", True))
    enable_validator_agent = bool(get_admin_flag("workflow.enable_validator_agent", True))
    enable_constraint_validation = llm_enabled and bool(get_admin_flag("llm.enable_constraint_validation", True))

    treatment_plan = str(state.get("treatment_plan") or "").strip()
    prevention_advice = str(state.get("prevention_advice") or "").strip()
    if not treatment_plan or not prevention_advice:
        if enable_treatment_generation:
            return "treatment", False, "番茄病害监督智能体：缺少治疗/预防方案，进入治疗方案智能体", ["missing_treatment_or_prevention"]
        return "end", True, "番茄病害监督智能体：管理员已关闭治疗生成，跳过治疗阶段", ["treatment_generation_disabled"]

    should_run_verification = enable_validator_agent and enable_constraint_validation
    if state.get("verification_result") is None:
        if should_run_verification:
            return "verification", False, "番茄病害监督智能体：治疗方案已生成，进入农业合规审查", ["missing_verification"]
        return "end", True, "番茄病害监督智能体：管理员已关闭合规审查，流程结束", ["verification_disabled"]

    if state.get("verification_passed") is False:
        if not should_run_verification:
            return "end", True, "番茄病害监督智能体：合规审查关闭，忽略未通过结果", ["verification_disabled_skip_fail"]
        rewrite_count = int(state.get("rewrite_count") or 0)
        raw_rewrite_limit = get_admin_flag("workflow.validator_rewrite_limit", 1)
        rewrite_limit = int(1 if raw_rewrite_limit is None else raw_rewrite_limit)
        if rewrite_count >= rewrite_limit:
            return "end", True, "番茄病害监督智能体：审查未通过且达到重写上限，建议后续转入专家复核", ["verification_failed_max_retry"]

        state["rewrite_count"] = rewrite_count + 1
        return "treatment", False, "番茄病害监督智能体：审查未通过，回到治疗方案智能体重写", ["verification_failed_rewrite"]

    return "end", True, "番茄病害监督智能体：治疗方案已通过农业合规审查，流程结束", ["all_required_outputs_ready"]
def supervisor_agent(state: CropDiseaseState) -> CropDiseaseState:
    """监督智能体：执行确定性路由并带循环保护。"""
    print("\n[番茄病害监督智能体] 协调流程...")
    current_step = state.get("current_step", "start")
    flags = state.get("personalization_flags", {}) or {}
    history = state.get("history", [])
    step_count = int(state.get("step_count") or 0) + 1
    state["step_count"] = step_count
    missing_profile_fields = list(flags.get("missing_profile_fields") or [])
    follow_ups = normalize_follow_up_questions([
        *(flags.get("follow_up_questions") or []),
        *build_missing_field_questions(missing_profile_fields),
    ])
    flags["follow_up_questions"] = follow_ups
    state["follow_up_questions"] = follow_ups
    state["personalization_flags"] = flags
    query_text = str(state.get("user_query") or "")
    has_uploaded_image_hint = any(token in query_text for token in ["图片路径", "图像路径", "path:", "path：", ".jpg", ".jpeg", ".png", ".webp"])
    if has_uploaded_image_hint and not state.get("image_path"):
        state["next_action"] = "reception"
        state["is_complete"] = False
        state["messages"] = ["番茄病害监督智能体：检测到有上传图片但尚未解析路径，先回接待智能体补全 image_path"]
        history.append((current_step, "reception"))
        state["history"] = history[-20:]
        append_trace(
            state,
            agent="supervisor",
            inputs={"current_step": current_step, "step_count": step_count, "image_path": state.get("image_path")},
            outputs={"next_action": "reception", "is_complete": False},
            decision={"next_action": "reception", "reasons": ["image_path_missing"], "reason": "image_path_missing"},
        )
        return state
    if step_count > 12:
        workflow_error = f"SUPERVISOR_STEP_GUARD_EXCEEDED(step_count={step_count})"
        state["workflow_error"] = workflow_error
        state["next_action"] = "end"
        state["is_complete"] = True
        state["messages"] = ["番茄病害监督智能体：触发步骤上限保护，强制结束流程"]
        append_trace(
            state,
            agent="supervisor",
            inputs={
                "current_step": current_step,
                "step_count": step_count,
                "missing_profile_fields": missing_profile_fields,
                "follow_up_questions": follow_ups,
            },
            outputs={"next_action": "end", "is_complete": True},
            decision={
                "next_action": "end",
                "reasons": ["step_count_guard"],
                "reason": workflow_error,
                "reason_str": workflow_error,
            },
        )
        return state
    next_action, is_complete, message, decision_reasons = _deterministic_supervisor_decision(
        state,
        flags,
        missing_profile_fields,
    )
    if history and history[-1] == (current_step, next_action):
        workflow_error = f"SUPERVISOR_LOOP_GUARD(state={current_step}, action={next_action})"
        state["workflow_error"] = workflow_error
        next_action = "end"
        is_complete = True
        message = "番茄病害监督智能体：检测到同状态重复路由，触发循环保护并结束"
        decision_reasons = ["repeat_same_state_action", workflow_error]
    state["next_action"] = next_action
    state["is_complete"] = is_complete
    state["messages"] = [message]
    history.append((current_step, next_action))
    state["history"] = history[-20:]
    print(f"  - 当前步骤: {current_step}")
    print(f"  - 步骤计数: {step_count}")
    print(f"  - 下一步动作: {next_action}")
    print(f"  - 是否完成: {is_complete}")
    append_trace(
        state,
        agent="supervisor",
        inputs={
            "current_step": current_step,
            "disease_type": state.get("disease_type"),
            "disease_confidence": state.get("disease_confidence"),
            "symptoms": state.get("symptoms"),
            "image_path": state.get("image_path"),
            "step_count": step_count,
            "missing_profile_fields": missing_profile_fields,
            "follow_up_questions": follow_ups,
        },
        outputs={"next_action": next_action, "is_complete": is_complete},
        decision={
            "next_action": next_action,
            "reasons": decision_reasons,
            "reason_str": message,
            "reason": message,
            "workflow_error": state.get("workflow_error"),
            "model_info": state.get("diagnosis_model_meta"),
        },
    )
    return state
def kb_retrieval_agent(state: CropDiseaseState) -> CropDiseaseState:
    """
    知识检索智能体节点（基于知识库检索）
    Args:
        state: 当前系统状态
    Returns:
        更新后的状态
    """
    disease_type = state.get("final_disease") or state.get("disease_type")
    kb = get_kb_manager()
    disease_description = kb.get_disease_description(disease_type)
    plan = kb.get_treatment_plan(disease_type)
    kb_snapshot = {
        "disease": disease_type,
        "description": disease_description,
        "treatment": plan.get("treatment"),
        "prevention": plan.get("prevention"),
        "actions": _normalize_kb_actions(plan.get("actions")),
        "ingredients": [str(item).strip() for item in (plan.get("ingredients") or []) if str(item).strip()],
    }
    state["kb_snapshot"] = kb_snapshot
    state["current_step"] = "kb_retrieval_complete"
    state["messages"] = [f"知识检索智能体：已补全{disease_type}的知识信息"]
    append_trace(
        state,
        agent="kb_retrieval",
        inputs={"disease_type": disease_type},
        outputs=kb_snapshot,
    )
    return state
def _rule_based_supervisor(current_step: str, state: CropDiseaseState, flags: dict) -> tuple:
    """番茄病害规则决策（后备方案）"""
    disease_confidence = state.get("disease_confidence") or 0
    if (
        current_step == "diagnosis_complete"
        and flags.get("confirm_when_low_confidence")
        and disease_confidence < float(get_runtime_thresholds()["diagnosis_conf_threshold"])
        and not state.get("final_disease")
    ):
        return "reception", False, "番茄病害监督智能体：置信度低且无有效诊断，回到接待追问补充信息"
    if current_step == "start":
        return "reception", False, "番茄病害监督智能体：开始诊断流程，转发至接待智能体"
    elif current_step == "reception_complete":
        return "diagnosis", False, "番茄病害监督智能体：信息收集完成，转发至诊断智能体"
    elif current_step == "diagnosis_complete":
        if state.get("final_disease"):
            return "kb_retrieval", False, "番茄病害监督智能体：诊断完成，转发至知识检索智能体"
        return "end", True, "番茄病害监督智能体：无法诊断病害，流程结束"
    elif current_step == "kb_retrieval_complete":
        return "treatment", False, "番茄病害监督智能体：知识检索完成，转发至治疗方案智能体"
    elif current_step == "treatment_complete":
        return "end", True, "番茄病害监督智能体：治疗方案生成完成，诊断流程结束"
    else:
        return "end", True, "番茄病害监督智能体：未知状态，流程结束"
