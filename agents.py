"""
智能体节点模块
定义各个智能体的具体实现
"""
from state import CropDiseaseState
from llm_utils import call_llm, extract_json_from_response
from diagnosis_model import get_diagnosis_engine
from knowledge_base import get_kb_manager
from config import DIAGNOSIS_CONFIDENCE_THRESHOLD
from personalization.profile_models import FarmerProfile, BaseProfile, TreatmentConstraint
from personalization.profile_rules import filter_treatment_by_constraints
from trace_store import append_trace_event
from typing import Optional
import re
import json
import os


# 获取知识库管理器实例
kb_manager = get_kb_manager()


def append_trace(
    state: CropDiseaseState,
    agent: str,
    inputs: dict,
    outputs: dict,
    decision: dict | str | None = None,
) -> None:
    event = {
        "agent": agent,
        "inputs": inputs,
        "outputs": outputs,
        "step": state.get("current_step"),
    }
    if decision is not None:
        event["decision"] = decision
    state.setdefault("trace_events", []).append(event)
    trace_id = state.get("trace_id")
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
    
    # 验证图像路径是否存在
    if image_path and not os.path.exists(image_path):
        print(f"警告：图像路径不存在：{image_path}")
        # 尝试查找相似文件名
        import glob
        base_name = os.path.basename(image_path)
        possible_files = glob.glob(f"*{base_name}*") + glob.glob(f"*/*{base_name}*")
        if possible_files:
            print(f"找到可能的图像文件：{possible_files[0]}")
            image_path = possible_files[0]
        else:
            image_path = None
    
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

    try:
        response = call_llm(cleaned_query, system_prompt, temperature=0.3)
        result = extract_json_from_response(response)
        
        if result:
            crop_growth_stage = result.get("growth_stage")
            symptoms = result.get("symptoms", [])
        else:
            # 如果JSON解析失败，使用规则匹配作为后备
            _, crop_growth_stage, symptoms = _fallback_extraction(cleaned_query)
    except Exception as e:
        print(f"大模型调用失败，使用规则匹配: {e}")
        _, crop_growth_stage, symptoms = _fallback_extraction(cleaned_query)

    # 强制设置作物类型为番茄
    crop_type = "番茄"
    _fill_missing_from_profile(state, base_profile)

    missing_profile_fields = _find_missing_profile_fields(base_profile)
    
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
        state["personalization_flags"] = flags
    message = "，".join(message_parts)

    # 更新状态
    state["crop_type"] = crop_type
    state["crop_growth_stage"] = crop_growth_stage
    state["symptoms"] = symptoms
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
    """
    番茄病害诊断智能体节点（使用深度学习模型）

    职责：
    1. 基于症状和图像进行番茄病害诊断
    2. 确定番茄病害类型和置信度
    3. 提供病害详细描述

    Args:
        state: 当前系统状态

    Returns:
        更新后的状态
    """
    print("\n[番茄病害诊断智能体] 正在分析病害...")

    crop_type = state.get("crop_type", "番茄")  # 确保是番茄
    symptoms = state.get("symptoms", [])
    crop_growth_stage = state.get("crop_growth_stage")
    image_path = state.get("image_path")
    flags = state.get("personalization_flags", {}) or {}
    priors = {
        "facility": flags.get("facility"),
        "province": flags.get("province"),
    }
    personalization_context = state.get("personalization_context")
    
    # 使用深度学习诊断引擎
    diagnosis_engine = get_diagnosis_engine()
    disease_type = None
    final_disease = None
    disease_confidence = None
    disease_description = None
    image_top3 = []
    
    # 优先使用图像诊断（如果提供了图像路径）
    if image_path:
        print(f"[番茄病害诊断智能体] 使用图像进行诊断: {image_path}")
        try:
            disease_type, disease_confidence, probs_dict = diagnosis_engine.diagnose_from_image(image_path)
            image_top3 = sorted(probs_dict.items(), key=lambda x: x[1], reverse=True)[:3]
            if disease_type:
                final_disease = disease_type
            top1_conf = float(image_top3[0][1]) if image_top3 else float(disease_confidence or 0.0)
            top2_conf = float(image_top3[1][1]) if len(image_top3) > 1 else None
            state["image_diagnosis"] = {
                "image_path": image_path,
                "top1": {"disease": disease_type, "confidence": float(disease_confidence or 0.0)},
                "top3": [(name, float(prob)) for name, prob in image_top3],
            }

            disease_confidence = top1_conf
            if top1_conf < DIAGNOSIS_CONFIDENCE_THRESHOLD:
                flags["need_confirm"] = True
                flags.setdefault("fallback_reason", []).append("low_confidence")
            if top2_conf is not None and (top1_conf - top2_conf) < 0.15:
                flags["need_confirm"] = True
                flags.setdefault("fallback_reason", []).append("low_margin")

            # 获取病害描述
            disease_description = diagnosis_engine._get_disease_description(disease_type, symptoms)
            print(f"[番茄病害诊断智能体] 图像诊断成功")
        except Exception as e:
            print(f"[番茄病害诊断智能体] 图像诊断失败: {e}，使用症状诊断")
    
    # 如果图像诊断失败或没有图像，使用症状诊断
    if (not disease_type) and (not image_path or symptoms):
        print("[番茄病害诊断智能体] 使用症状进行诊断")
        try:
            disease_type, disease_confidence, disease_description = diagnosis_engine.diagnose_from_symptoms(
                crop_type=crop_type,
                symptoms=symptoms,
                growth_stage=crop_growth_stage
            )
            if disease_type:
                final_disease = disease_type
        except Exception as e:
            print(f"诊断模型调用失败: {e}，使用规则匹配")
            # 后备方案：规则匹配
            disease_type, disease_confidence, disease_description = _rule_based_diagnosis(
                crop_type, symptoms, priors=priors
            )
            if disease_type:
                final_disease = disease_type
    elif image_path and flags.get("need_confirm") and symptoms:
        print("[番茄病害诊断智能体] 低置信度，使用症状进行回退诊断")
        try:
            disease_type, disease_confidence, disease_description = diagnosis_engine.diagnose_from_symptoms(
                crop_type=crop_type,
                symptoms=symptoms,
                growth_stage=crop_growth_stage
            )
            if disease_type:
                final_disease = disease_type
        except Exception as e:
            print(f"诊断模型调用失败: {e}，使用规则匹配")
            disease_type, disease_confidence, disease_description = _rule_based_diagnosis(
                crop_type, symptoms, priors=priors
            )
            if disease_type:
                final_disease = disease_type

    if personalization_context and disease_type:
        personalization_prompt = f"""以下是诊断结果，请结合农户个性化上下文给出补充提示：
诊断病害：{disease_type}
症状：{symptoms}
个性化上下文：{personalization_context}
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

    disease_confidence = disease_confidence or 0.0
    message = f"番茄病害诊断智能体：诊断为{disease_type}，置信度={disease_confidence:.2%}"
    if image_path and state.get("image_diagnosis"):
        image_top1 = state["image_diagnosis"].get("top1", {})
        top3_text = ", ".join([f"{name}={prob:.2f}" for name, prob in state["image_diagnosis"].get("top3", [])])
        message += (
            f"\n图像诊断证据："
            f"\n- Image: {image_path}"
            f"\n- Top1: {image_top1.get('disease')} (conf={float(image_top1.get('confidence', 0.0)):.2f})"
            f"\n- Top3: {top3_text}"
        )
    if personalization_context:
        message += "（已参考个性化上下文）"

    if flags.get("confirm_when_low_confidence") and disease_confidence < DIAGNOSIS_CONFIDENCE_THRESHOLD:
        follow_ups = _build_follow_up_questions(symptoms, flags, state)
        if follow_ups:
            flags["follow_up_questions"] = follow_ups
            message += f"；建议追问：{'；'.join(follow_ups)}"
        flags["need_confirm"] = True
        flags.setdefault("fallback_reason", []).append("low_confidence")
        state["personalization_flags"] = flags

    # 更新状态
    if final_disease:
        disease_type = final_disease
    state["final_disease"] = final_disease
    state["disease_type"] = disease_type
    state["disease_confidence"] = disease_confidence
    state["disease_description"] = disease_description
    state["current_step"] = "diagnosis_complete"
    state["messages"] = [message]

    print(f"  - 病害类型: {disease_type}")
    print(f"  - 置信度: {disease_confidence:.2%}")
    print(f"  - 描述: {disease_description}")
    if flags.get("follow_up_questions"):
        print(f"  - 追问建议: {flags['follow_up_questions']}")

    append_trace(
        state,
        agent="diagnosis",
        inputs={
            "crop_type": crop_type,
            "crop_growth_stage": crop_growth_stage,
            "symptoms": symptoms,
            "image_path": image_path,
        },
        outputs={
            "disease_type": disease_type,
            "final_disease": final_disease,
            "disease_confidence": disease_confidence,
            "disease_description": disease_description,
            "image_diagnosis": state.get("image_diagnosis"),
            "image_top1": (state.get("image_diagnosis") or {}).get("top1"),
            "follow_up_questions": flags.get("follow_up_questions"),
            "need_confirm": flags.get("need_confirm"),
            "fallback_reason": flags.get("fallback_reason"),
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
    crop_type = "番茄"  # 确保是番茄
    crop_growth_stage = state.get("crop_growth_stage")
    disease_description = state.get("disease_description", "")
    profile, _ = _get_profile_from_state(state)
    constraints = TreatmentConstraint()
    if profile:
        constraints = profile.constraints
    flags = state.get("personalization_flags", {}) or {}
    constraint_brief = _summarize_constraints(constraints)
    
    kb_snapshot = state.get("kb_snapshot") or {}
    if kb_snapshot.get("treatment") or kb_snapshot.get("prevention"):
        treatment_plan = kb_snapshot.get("treatment", "")
        prevention_advice = kb_snapshot.get("prevention", "")
    else:
        # 使用大模型生成治疗方案
        prompt = f"""请为以下番茄病害制定详细的治疗方案和预防建议：

作物类型：{crop_type}
生长阶段：{crop_growth_stage or '未知'}
病害类型：{disease_type}
病害描述：{disease_description}
个性化上下文：{state.get('personalization_context') or '无'}
治疗约束：{constraint_brief}

请提供：
1. 具体的治疗方案（包括推荐药物、使用方法、使用频率等）
2. 预防措施（包括栽培管理、环境控制等）

请以JSON格式返回，格式如下：
{{
    "treatment": "详细的治疗方案",
    "prevention": "预防建议（多条用换行分隔）"
}}"""

        system_prompt = (
            "你是一位经验丰富的番茄病害防治专家，擅长制定番茄病害的专业、实用、安全的治疗方案和预防建议。"
        )

        try:
            response = call_llm(prompt, system_prompt, temperature=0.7)
            result = extract_json_from_response(response)
            
            if result:
                treatment_plan = result.get("treatment", "")
                prevention_advice = result.get("prevention", "")
            else:
                # 如果解析失败，使用知识库作为后备
                treatment_plan, prevention_advice = _get_treatment_from_knowledge_base(disease_type)
        except Exception as e:
            print(f"大模型调用失败，使用知识库: {e}")
            treatment_plan, prevention_advice = _get_treatment_from_knowledge_base(disease_type)

    if constraints:
        treatment_plan, dropped = filter_treatment_by_constraints(treatment_plan, constraints, flags)
        if dropped:
            flags["filtered_components"] = dropped
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
            "filtered_components": flags.get("filtered_components"),
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


def _find_missing_profile_fields(base_profile: Optional[BaseProfile]) -> list[str]:
    """检查档案中缺少的关键字段，提示追问。"""
    if not base_profile:
        return ["base_id", "location", "growth_stage"]
    missing = []
    if not base_profile.location:
        missing.append("location")
    if not base_profile.growth_stage:
        missing.append("growth_stage")
    if not base_profile.environment:
        missing.append("environment")
    return missing


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


def supervisor_agent(state: CropDiseaseState) -> CropDiseaseState:
    """
    番茄病害监督智能体节点（使用大模型API进行智能决策）

    职责：
    1. 协调番茄病害诊断流程
    2. 决定下一步执行哪个智能体
    3. 判断流程是否完成

    Args:
        state: 当前系统状态

    Returns:
        更新后的状态，包含next_action字段
    """
    print("\n[番茄病害监督智能体] 协调流程...")

    current_step = state.get("current_step", "start")
    messages = state.get("messages", [])
    flags = state.get("personalization_flags", {}) or {}
    personalization_context = state.get("personalization_context") or "无"
    follow_ups = flags.get("follow_up_questions", [])
    
    # 获取历史next_action，防止无限循环
    history = state.get("history", [])
    
    # 使用大模型进行智能决策
    context = f"""
当前番茄病害诊断流程状态：
- 当前步骤：{current_step}
- 作物类型：番茄
- 生长阶段：{state.get('crop_growth_stage', '未识别')}
- 症状：{state.get('symptoms', [])}
- 病害类型：{state.get('disease_type', '未诊断')}
- 诊断置信度：{state.get('disease_confidence') or 0:.2%}
- 历史消息：{messages[-3:] if messages else '无'}
- 个性化上下文：{personalization_context}
- 追问建议：{follow_ups or '无'}
"""

    prompt = f"""{context}

请根据当前状态决定下一步操作。可选操作：
1. "reception" - 转到接待智能体（信息收集）
2. "diagnosis" - 转到诊断智能体（病害诊断）
3. "kb_retrieval" - 转到知识检索智能体（知识补全）
4. "treatment" - 转到治疗方案智能体（生成治疗方案）
5. "end" - 结束流程
若诊断置信度低于{DIAGNOSIS_CONFIDENCE_THRESHOLD:.2%}且农户要求低置信度需确认，请返回"reception"追问补充信息（可参考追问建议）。

请以JSON格式返回，格式如下：
{{
    "next_action": "下一步操作",
    "is_complete": true/false,
    "reason": "决策理由"
}}"""

    system_prompt = f"""你是一个智能流程协调器，负责协调番茄病害诊断流程。
流程顺序：start -> reception -> diagnosis -> kb_retrieval -> treatment -> end
当current_step为start时，必须先执行reception
当current_step为reception_complete时，必须执行diagnosis
当current_step为diagnosis_complete时，必须执行kb_retrieval
当current_step为kb_retrieval_complete时，必须执行treatment
当current_step为treatment_complete时，必须执行end
如果信息不完整，可以返回reception重新收集。
如果诊断置信度低于{DIAGNOSIS_CONFIDENCE_THRESHOLD:.2%}且农户要求确认，请返回reception追问。
如果所有步骤完成，返回end。"""

    decision_reason = ""
    try:
        response = call_llm(prompt, system_prompt, temperature=0.3)
        result = extract_json_from_response(response)
        
        if result:
            next_action = result.get("next_action", "end")
            # 验证next_action的有效性，防止无效值导致循环
            valid_actions = ["reception", "diagnosis", "kb_retrieval", "treatment", "end"]
            if next_action not in valid_actions:
                print(f"无效的next_action: {next_action}，使用规则决策")
                next_action, is_complete, message = _rule_based_supervisor(current_step, state, flags)
            else:
                is_complete = result.get("is_complete", True)
                reason = result.get("reason", "")
                decision_reason = reason
                message = f"番茄病害监督智能体：{reason or f'下一步操作：{next_action}'}"
        else:
            # 如果解析失败，使用规则决策
            next_action, is_complete, message = _rule_based_supervisor(current_step, state, flags)
    except Exception as e:
        print(f"大模型调用失败，使用规则决策: {e}")
        next_action, is_complete, message = _rule_based_supervisor(current_step, state, flags)
        decision_reason = message

    if not decision_reason:
        hints = []
        if state.get("image_path"):
            hints.append("has_image")
        if not state.get("symptoms"):
            hints.append("symptoms_missing")
        if (state.get("disease_confidence") or 0) < DIAGNOSIS_CONFIDENCE_THRESHOLD:
            hints.append("low_confidence")
            if state.get("final_disease"):
                hints.append("need_confirm_but_continue")
        if current_step == "diagnosis_complete":
            hints.append("post_diagnosis")
        decision_reason = ", ".join(hints) or message

    # 更新状态
    if current_step == "diagnosis_complete" and state.get("final_disease") and next_action == "end":
        next_action = "kb_retrieval"
        is_complete = False
        message = "番茄病害监督智能体：诊断已完成，继续进入知识检索智能体"
    state["next_action"] = next_action
    state["is_complete"] = is_complete
    state["messages"] = [message]
    
    # 添加历史记录，防止无限循环
    history.append((current_step, next_action))
    # 只保留最近的10个历史记录
    state["history"] = history[-10:]
    
    # 检查是否出现重复的动作序列（超过3次）
    if len(history) > 6:
        recent_sequence = tuple(history[-3:])
        if history.count(recent_sequence) > 2:
            print("检测到重复动作序列，强制结束流程")
            state["next_action"] = "end"
            state["is_complete"] = True

    print(f"  - 当前步骤: {current_step}")
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
        },
        outputs={"next_action": next_action, "is_complete": is_complete},
        decision={"next_action": next_action, "reason": decision_reason},
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
