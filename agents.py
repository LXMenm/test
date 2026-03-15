"""
智能体节点模块
定义各个智能体的具体实现
"""
from state import CropDiseaseState
from llm_utils import call_llm, extract_json_from_response
from diagnosis_model import get_diagnosis_engine
from knowledge_base import get_kb_manager
from config import DIAGNOSIS_CONFIDENCE_THRESHOLD, DIAGNOSIS_ALLOW_TORCH
from confidence_policy import make_confidence_flags
from personalization.profile_models import FarmerProfile, BaseProfile, TreatmentConstraint
from personalization.profile_rules import apply_personalization_to_treatment, normalize_filter_outputs
from personalization.utils import (
    dedupe_reasons,
    compute_personalization_applied,
    build_missing_field_questions,
    normalize_follow_up_questions,
)
from trace_store import append_trace_event
from datetime import datetime, timezone
from typing import Optional
from model_registry import resolve_model
from pydantic import BaseModel, Field, ValidationError
import re
import json
from pathlib import Path
# 获取知识库管理器实例
kb_manager = get_kb_manager()
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
            flags["follow_up_questions"] = follow_ups[:3]
            state["follow_up_questions"] = follow_ups[:3]
        state["personalization_flags"] = flags
    message = "，".join(message_parts)
    # 更新状态
    state["crop_type"] = crop_type
    state["crop_growth_stage"] = crop_growth_stage
    normalized_symptoms = kb_manager.normalize_symptoms(symptoms)
    state["symptoms"] = symptoms
    state["structured_symptoms"] = {"normalized_symptoms": normalized_symptoms}
    state["image_path"] = image_path
    state["current_step"] = "reception_complete"
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
            "crop_growth_stage": crop_growth_stage,
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
    crop_growth_stage = state.get("crop_growth_stage")
    image_path = state.get("image_path")
    flags = state.get("personalization_flags", {}) or {}
    flags["need_confirm"] = False
    policy = state.get("personalization_policy") or {}
    hard_constraints = policy.get("hard_constraints") if isinstance(policy, dict) else {}
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

    image_probs: dict[str, float] = {}
    text_probs: dict[str, float] = {}
    prior_probs: dict[str, float] = {}
    fusion_probs: dict[str, float] = {}
    image_confidence = 0.0

    # 图像分支
    if image_path:
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

    # 文本分支（KB 驱动）
    try:
        if hasattr(diagnosis_engine, "predict_text_proba"):
            text_probs = diagnosis_engine.predict_text_proba(
                symptoms=normalized_symptoms,
                growth_stage=crop_growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )
        else:
            text_probs = kb_manager.score_diseases_from_text(
                crop_type=crop_type,
                symptoms=normalized_symptoms,
                growth_stage=crop_growth_stage,
                environment=environment,
                facility=facility,
                province=province,
            )
    except Exception as e:
        print(f"[番茄病害诊断智能体] 文本分支失败: {e}")
        text_probs = {}

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

    # 融合分支
    if hasattr(diagnosis_engine, "fuse_multimodal_probs"):
        fusion_probs, weights = diagnosis_engine.fuse_multimodal_probs(
            image_probs=image_probs,
            text_probs=text_probs,
            prior_probs=prior_probs,
            image_confidence=image_confidence,
        )
    else:
        # 兼容旧引擎：简单回退
        fusion_probs = image_probs or text_probs or prior_probs or {"健康": 1.0}
        weights = {"image": 1.0 if image_probs else 0.0, "text": 1.0 if text_probs and not image_probs else 0.0, "prior": 0.0}

    image_top3 = sorted(image_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    text_top3 = sorted(text_probs.items(), key=lambda x: x[1], reverse=True)[:3]
    fusion_top3 = sorted(fusion_probs.items(), key=lambda x: x[1], reverse=True)[:3]

    image_top1 = image_top3[0][0] if image_top3 else None
    text_top1 = text_top3[0][0] if text_top3 else None
    text_confidence = float(text_top3[0][1]) if text_top3 else 0.0
    final_disease = fusion_top3[0][0] if fusion_top3 else (image_top1 or text_top1 or "健康")
    final_confidence = float(fusion_top3[0][1]) if fusion_top3 else max(image_confidence, text_confidence, 0.0)

    modality_conflict_flag = bool(
        image_top1 and text_top1 and image_top1 != text_top1 and image_confidence >= 0.6 and text_confidence >= 0.6
    )

    if hasattr(diagnosis_engine, "build_diagnosis_evidence"):
        diagnosis_evidence = diagnosis_engine.build_diagnosis_evidence(
            normalized_symptoms=normalized_symptoms,
            image_probs=image_probs,
            text_probs=text_probs,
            fusion_probs=fusion_probs,
            weights=weights,
            modality_conflict_flag=modality_conflict_flag,
        )
    else:
        diagnosis_evidence = {
            "normalized_symptoms": normalized_symptoms,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "fusion_top3": fusion_top3,
            "weights": weights,
            "modality_conflict_flag": modality_conflict_flag,
            "summary": f"融合诊断Top1: {final_disease}",
        }

    confidence_policy = make_confidence_flags(fusion_top3, fallback_confidence=float(final_confidence or 0.0))
    if confidence_policy.get("need_confirm"):
        flags["need_confirm"] = True
        flags["fallback_reason"] = list(confidence_policy.get("reasons") or [])

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

    if flags.get("confirm_when_low_confidence") and final_confidence < DIAGNOSIS_CONFIDENCE_THRESHOLD:
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
            flags["follow_up_questions"] = follow_ups
            state["follow_up_questions"] = follow_ups
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", [])
        if "low_confidence" not in flags["fallback_reason"]:
            flags["fallback_reason"].append("low_confidence")

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
    state["final_source"] = "fusion"
    state["disease_description"] = disease_description
    state["image_probs"] = image_probs
    state["text_probs"] = text_probs
    state["prior_probs"] = prior_probs
    state["fusion_probs"] = fusion_probs
    state["text_top3"] = [(name, float(prob)) for name, prob in text_top3]
    state["fusion_top3"] = [(name, float(prob)) for name, prob in fusion_top3]
    state["diagnosis_evidence"] = diagnosis_evidence
    state["modality_conflict_flag"] = modality_conflict_flag
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
            "weights": weights,
            "image_top3": image_top3,
            "text_top3": text_top3,
            "fusion_top3": fusion_top3,
            "modality_conflict_flag": modality_conflict_flag,
            "diagnosis_evidence": diagnosis_evidence,
            "follow_up_questions": flags.get("follow_up_questions"),
            "need_confirm": flags.get("need_confirm"),
            "fallback_reason": flags.get("fallback_reason"),
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
        "白粉病": {
            "symptoms": ["白粉", "斑点"],
            "confidence": 0.87,
            "description": "白粉病在叶片表面形成白色粉状物，影响光合作用，导致叶片早衰。"
        },
        "细菌性斑点病": {
            "symptoms": ["斑点", "变色"],
            "confidence": 0.81,
            "description": "细菌性病害，在叶片和果实上形成小斑点，逐渐扩大并可能穿孔。"
        },
        "灰霉病": {
            "symptoms": ["腐烂", "霉斑"],
            "confidence": 0.84,
            "description": "灰霉病在潮湿环境下发生，导致果实和叶片腐烂，表面产生灰色霉层。"
        }
    }
    
    # 如果没有症状，判断为健康
    if not symptoms:
        return "健康", 0.99, "番茄植株生长正常，无病害症状。"
    
    # 匹配症状最相似的病害
    best_match = None
    max_score = 0
    
    for disease, info in disease_knowledge.items():
        if disease == "健康":
            continue
        
        # 计算症状匹配得分
        match_score = 0
        for symptom in symptoms:
            for disease_symptom in info["symptoms"]:
                if disease_symptom in symptom:
                    match_score += 1
        match_score *= _get_prior_weight(disease, priors)
        
        if match_score > max_score:
            max_score = match_score
            best_match = disease
    
    # 如果找到匹配的病害
    if best_match and max_score > 0:
        info = disease_knowledge[best_match]
        return best_match, info["confidence"], info["description"]
    else:
        # 没有找到匹配的病害，返回未知
        return "未知病害", 0.5, "无法根据症状确定具体的番茄病害类型，建议提供更多信息或病害图像。"
def _get_prior_weight(disease: str, priors: dict) -> float:
    """根据设施/省份对规则诊断打先验权重。"""
    facility = priors.get("facility") or ""
    province = priors.get("province") or ""
    facility_weights = {
        "温室": {"灰霉病": 1.2, "白粉病": 1.1},
        "温室大棚": {"灰霉病": 1.2, "白粉病": 1.1},
        "露地": {"早疫病": 1.1, "晚疫病": 1.1},
    }
    province_weights = {
        "山东": {"早疫病": 1.05, "晚疫病": 1.05},
        "云南": {"灰霉病": 1.08, "叶霉病": 1.05},
    }
    weight = 1.0
    for name, mapping in facility_weights.items():
        if name in facility:
            weight *= mapping.get(disease, 1.0)
    for name, mapping in province_weights.items():
        if name in province:
            weight *= mapping.get(disease, 1.0)
    return weight
def _build_follow_up_questions(symptoms: list, flags: dict, state: CropDiseaseState) -> list[str]:
    """在低置信度时生成追问要点。"""
    questions = []
    if not state.get("image_path"):
        questions.append("是否有清晰的叶片/果实近照可供诊断？")
    if state.get("crop_growth_stage") is None:
        questions.append("当前番茄处于哪个生育期？")
    if state.get("environment") is None:
        questions.append("近期棚室/田间的温湿度或天气变化情况？")
    if symptoms:
        questions.append("症状扩散速度和面积如何变化？")
    if flags.get("harvest_window_days"):
        questions.append("距离计划采收的具体时间？")
    return questions[:3]
def _resolve_treatment_branch(flags: dict) -> str:
    farm_scale = str(flags.get("farm_scale") or "SMALL")
    pesticide_access_level = str(flags.get("pesticide_access_level") or "LIMITED")
    equipment = [str(item) for item in (flags.get("equipment") or [])]
    if farm_scale in {"BALCONY", "SMALL"}:
        branch = "FAMILY"
    elif farm_scale == "MEDIUM":
        branch = "MID"
    else:
        branch = "ENTERPRISE"
    if pesticide_access_level == "NONE":
        return "FAMILY"
    if branch == "ENTERPRISE" and not equipment and pesticide_access_level != "FULL":
        branch = "MID"
    if (
        branch == "MID"
        and any(item in {"DRONE", "MIST_BLOWER"} for item in equipment)
        and pesticide_access_level == "FULL"
        and farm_scale == "GREENHOUSE_LARGE"
    ):
        branch = "ENTERPRISE"
    return branch
def _contains_any(text: str, keywords: list[str]) -> bool:
    lower = text.lower()
    return any(keyword.lower() in lower for keyword in keywords)
def _validate_treatment_output(
    *,
    branch: str,
    hard_constraints: dict,
    flags: dict,
    treatment_text: str,
    prevention_text: str,
) -> list[str]:
    violations: list[str] = []
    whole_text = f"{treatment_text}\n{prevention_text}"
    equipment = [str(item) for item in (flags.get("equipment") or [])]
    pesticide_access_level = str(flags.get("pesticide_access_level") or "LIMITED")
    prefer_organic = bool(flags.get("prefer_organic"))
    drone_words = ["无人机", "drone"]
    enterprise_words = ["规模化", "sop", "标准作业", "监测", "复查", "轮换", "作用机制"]
    family_forbidden = ["无人机", "drone", "规模化喷施", "sop", "专业设备"]
    mid_forbidden = ["无人机", "drone"] if "DRONE" not in equipment else []
    if branch == "FAMILY":
        if _contains_any(whole_text, family_forbidden):
            violations.append("FAMILY 分支出现不可执行的企业/无人机流程")
        if pesticide_access_level == "NONE" and _contains_any(whole_text, ["购买", "专业杀虫", "专业杀菌", "资质"]):
            violations.append("FAMILY + 无购药能力时出现专业购药措辞")
    if branch == "MID" and mid_forbidden and _contains_any(whole_text, mid_forbidden):
        violations.append("MID 分支出现无人机流程")
    if branch == "ENTERPRISE":
        if "DRONE" not in equipment and _contains_any(whole_text, drone_words):
            violations.append("ENTERPRISE 在无 DRONE 设备时输出了无人机流程")
        if not _contains_any(whole_text, enterprise_words):
            violations.append("ENTERPRISE 缺少SOP/监测/轮换等企业化要素")
    forbidden_equipment_flows = [str(x) for x in (hard_constraints.get("forbidden_equipment_flows") or [])]
    if "DRONE" in forbidden_equipment_flows and _contains_any(whole_text, drone_words):
        violations.append("hard_constraints 禁止 DRONE 但文本出现无人机流程")
    banned_ingredients = [str(x).strip() for x in (hard_constraints.get("banned_ingredients") or []) if str(x).strip()]
    for ingredient in banned_ingredients:
        if ingredient in whole_text:
            violations.append(f"出现禁用成分: {ingredient}")
    harvest_window_days = hard_constraints.get("harvest_window_days")
    if harvest_window_days is None:
        harvest_window_days = flags.get("harvest_window_days")
    try:
        harvest_window_days = int(harvest_window_days)
    except Exception:
        harvest_window_days = None
    if harvest_window_days is not None and harvest_window_days <= 7 and not _contains_any(whole_text, ["采收", "安全间隔", "间隔期"]):
        violations.append("临近采收但缺少安全间隔提示")
    if prefer_organic and branch in {"FAMILY", "MID"} and _contains_any(whole_text, ["高毒", "强力化学", "专业化学农药"]):
        violations.append("prefer_organic 场景出现高风险化学措辞")
    return violations
def _apply_branch_post_fixes(branch: str, hard_constraints: dict, flags: dict, treatment_text: str, prevention_text: str) -> tuple[str, str]:
    text = treatment_text
    prevention = prevention_text
    if branch in {"FAMILY", "MID"} and str(flags.get("pesticide_access_level") or "") == "NONE":
        text = re.sub(r".*(专业杀虫|专业杀菌|需资质|必须购买).*(\n|$)", "", text, flags=re.IGNORECASE)
    forbidden_equipment_flows = [str(x) for x in (hard_constraints.get("forbidden_equipment_flows") or [])]
    if "DRONE" in forbidden_equipment_flows:
        text = re.sub(r".*(无人机|DRONE).*(\n|$)", "", text, flags=re.IGNORECASE)
        prevention = re.sub(r".*(无人机|DRONE).*(\n|$)", "", prevention, flags=re.IGNORECASE)
    harvest_window_days = hard_constraints.get("harvest_window_days")
    if harvest_window_days is None:
        harvest_window_days = flags.get("harvest_window_days")
    try:
        harvest_window_days = int(harvest_window_days)
    except Exception:
        harvest_window_days = None
    if harvest_window_days is not None and harvest_window_days <= 7 and not _contains_any(f"{text}\n{prevention}", ["采收", "安全间隔", "间隔期"]):
        notice = "【采收安全】距采收较近，请严格遵守采收安全间隔并优先低残留方案。"
        text = f"{text}\n{notice}".strip()
    return text.strip(), prevention.strip()
def _normalize_kb_actions(actions_like: object) -> dict:
    actions = actions_like if isinstance(actions_like, dict) else {}
    def _to_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
    treatment_plan = actions.get("treatment_plan") if isinstance(actions, dict) else {}
    treatment_plan = treatment_plan if isinstance(treatment_plan, dict) else {}
    return {
        "immediate_actions": _to_list(actions.get("immediate_actions") if isinstance(actions, dict) else []),
        "treatment_plan": {
            "FAMILY": _to_list(treatment_plan.get("FAMILY")),
            "MID": _to_list(treatment_plan.get("MID")),
            "ENTERPRISE": _to_list(treatment_plan.get("ENTERPRISE")),
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
    crop_growth_stage = state.get("crop_growth_stage")
    symptoms = state.get("symptoms") or []
    disease_description = state.get("disease_description", "")
    profile, base_profile = _get_profile_from_state(state)
    constraints = profile.constraints if profile else TreatmentConstraint()
    flags = state.get("personalization_flags", {}) or {}
    policy = state.get("personalization_policy") or {}
    policy_reasons = dedupe_reasons(state.get("personalization_reasons") or flags.get("personalization_reasons") or [])
    hard_constraints = policy.get("hard_constraints") if isinstance(policy, dict) else {}
    hard_constraints = hard_constraints if isinstance(hard_constraints, dict) else {}
    kb_snapshot = state.get("kb_snapshot") or {}
    base_info = {
        "facility": flags.get("facility") or (base_profile.facility if base_profile else None),
        "environment": flags.get("environment") or (base_profile.environment if base_profile else None),
        "growth_stage": flags.get("growth_stage") or (base_profile.growth_stage if base_profile else None),
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
    system_prompt = "你是番茄病害防治首席农艺师，输出必须专业、可执行、可审计，并严格遵守约束。"
    selected_branch = _resolve_treatment_branch(flags)
    flags["selected_branch"] = selected_branch
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
        state["crop_growth_stage"] = base_profile.growth_stage
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
def _build_profile_follow_up_questions(
    missing_fields: list[str],
    profile: Optional[FarmerProfile],
    base_profile: Optional[BaseProfile],
    policy: Optional[dict] = None,
) -> list[str]:
    """根据档案缺失项生成追问问句（仅用于待补充信息，不混入解释性 reasons）。"""
    _ = (profile, base_profile, policy)
    return build_missing_field_questions(missing_fields)[:3]

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
def _deterministic_supervisor_decision(state: CropDiseaseState, flags: dict, missing_profile_fields: list[str]) -> tuple[str, bool, str, list[str]]:
    """确定性路由，避免同态循环。"""
    # a) 无诊断结果 -> diagnosis
    has_diagnosis = bool(state.get("final_disease") or state.get("disease_type"))
    if not has_diagnosis:
        return "diagnosis", False, "番茄病害监督智能体：缺少诊断结果，先执行诊断智能体", ["missing_diagnosis"]
    # b) 仅 need_confirm 才回 reception（missing_profile_fields 仅作为提示，不阻断流程）
    if flags.get("need_confirm"):
        return "reception", False, "番茄病害监督智能体：需要补充确认信息，回到接待智能体", ["need_confirm"]
    # c) 无 kb_snapshot -> kb_retrieval
    if not state.get("kb_snapshot"):
        return "kb_retrieval", False, "番茄病害监督智能体：缺少知识快照，进入知识检索智能体", ["missing_kb_snapshot"]
    # d) 无 treatment_plan/prevention_advice -> treatment
    treatment_plan = str(state.get("treatment_plan") or "").strip()
    prevention_advice = str(state.get("prevention_advice") or "").strip()
    if not treatment_plan or not prevention_advice:
        return "treatment", False, "番茄病害监督智能体：缺少治疗/预防方案，进入治疗方案智能体", ["missing_treatment_or_prevention"]
    # e) 其他情况 end
    return "end", True, "番茄病害监督智能体：核心结果齐备，流程结束", ["all_required_outputs_ready"]
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
        and disease_confidence < DIAGNOSIS_CONFIDENCE_THRESHOLD
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
