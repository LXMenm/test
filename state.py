"""
状态管理模块
定义整个农作物病害诊治系统的状态结构
"""
from typing import TypedDict, List, Optional, Annotated, Dict, Any
import uuid
import operator
from personalization.profile_store import load_profile
from personalization.profile_context import (
    apply_base_profile_to_state,
    build_personalization_context,
    build_personalization_flags,
)
from personalization.profile_models import FarmerProfile, BaseProfile
from personalization.policy_engine import build_policy
from personalization.utils import dedupe_reasons, compute_personalization_applied


class CropDiseaseState(TypedDict):
    """
    农作物病害诊治系统的全局状态

    所有智能体共享此状态，并通过状态传递信息
    """
    # 用户输入的初始查询
    user_query: str

    # 作物基本信息
    crop_type: Optional[str]  # 作物类型（如：水稻、小麦、玉米等）
    crop_growth_stage: Optional[str]  # 生长阶段（如：苗期、拔节期、成熟期等）
    location: Optional[str]  # 地理位置
    province: Optional[str]  # 省份/区域
    facility: Optional[str]  # 种植设施类型（露地、温室等）
    environment: Optional[str]  # 近期环境备注

    # 症状信息（可能有多个症状）
    symptoms: List[str]  # 症状列表

    # 图像信息
    image_path: Optional[str]  # 病害图像路径

    # 诊断结果
    disease_type: Optional[str]  # 病害类型
    disease_confidence: Optional[float]  # 诊断置信度
    disease_description: Optional[str]  # 病害详细描述
    final_disease: Optional[str]  # 最终病害类型（统一字段）
    image_confidence: Optional[float]  # 图像模型top1置信度
    final_confidence: Optional[float]  # 最终结论置信度
    final_source: Optional[str]  # 最终结论来源
    diagnosis_model_id: Optional[str]  # 用户选择的模型ID
    diagnosis_model_meta: Optional[Dict[str, Any]]  # 最终使用模型信息

    structured_symptoms: Optional[Dict[str, Any]]
    text_confidence: Optional[float]
    text_top3: Optional[List[tuple[str, float]]]
    fusion_top3: Optional[List[tuple[str, float]]]
    diagnosis_evidence: Optional[Dict[str, Any]]
    modality_conflict_flag: Optional[bool]
    image_probs: Optional[Dict[str, float]]
    text_probs: Optional[Dict[str, float]]
    prior_probs: Optional[Dict[str, float]]
    fusion_probs: Optional[Dict[str, float]]
    normalized_symptoms: Optional[List[str]]
    fusion_meta: Optional[Dict[str, Any]]

    # 治疗方案
    treatment_plan: Optional[str]  # 具体治疗方案
    prevention_advice: Optional[str]  # 预防建议

    # 流程控制
    current_step: str  # 当前执行步骤
    next_action: Optional[str]  # 下一步动作
    is_complete: bool  # 是否完成整个流程
    step_count: int  # supervisor 调度计数
    workflow_error: Optional[str]  # 工作流降级/保护原因

    # 消息历史（用于记录各个智能体的输出）
    messages: Annotated[List[str], operator.add]

    # 历史操作记录（用于防止无限循环）
    history: List[tuple]

    # 错误信息
    error: Optional[str]  # 错误信息（如果有）

    # 个性化信息
    farmer_id: Optional[str]
    base_id: Optional[str]
    farmer_profile: Optional[Dict[str, Any]]
    personalization_context: Optional[str]
    personalization_flags: Dict[str, Any]
    personalization_policy: Optional[Dict[str, Any]]
    personalization_reasons: List[str]
    follow_up_questions: List[str]

    # Trace信息
    trace_id: str
    trace_events: List[Dict[str, Any]]
    kb_snapshot: Optional[Dict[str, Any]]


def create_initial_state(
    user_query: str, farmer_id: Optional[str] = None, base_id: Optional[str] = None
) -> CropDiseaseState:
    """
    创建初始状态

    Args:
        user_query: 用户的初始查询

    Returns:
        初始化的系统状态
    """
    state: CropDiseaseState = CropDiseaseState(
        user_query=user_query,
        crop_type=None,
        crop_growth_stage=None,
        location=None,
        province=None,
        facility=None,
        environment=None,
        symptoms=[],
        image_path=None,
        disease_type=None,
        disease_confidence=None,
        disease_description=None,
        final_disease=None,
        image_confidence=None,
        final_confidence=None,
        final_source=None,
        diagnosis_model_id=None,
        diagnosis_model_meta=None,
        structured_symptoms=None,
        text_confidence=None,
        text_top3=None,
        fusion_top3=None,
        diagnosis_evidence=None,
        modality_conflict_flag=None,
        image_probs=None,
        text_probs=None,
        prior_probs=None,
        fusion_probs=None,
        normalized_symptoms=None,
        fusion_meta=None,
        treatment_plan=None,
        prevention_advice=None,
        current_step="start",
        next_action=None,
        is_complete=False,
        step_count=0,
        workflow_error=None,
        messages=[],
        history=[],
        error=None,
        farmer_id=farmer_id,
        base_id=base_id,
        farmer_profile=None,
        personalization_context=None,
        personalization_flags={},
        personalization_policy=None,
        personalization_reasons=[],
        follow_up_questions=[],
        trace_id=uuid.uuid4().hex,
        trace_events=[],
        kb_snapshot=None,
    )

    if farmer_id:
        profile = load_profile(farmer_id)
        if profile:
            state["farmer_profile"] = profile.model_dump()
            resolved_base_id, base_profile = _resolve_base(profile, base_id)
            state["base_id"] = resolved_base_id
            apply_base_profile_to_state(state, base_profile)
            policy = None
            try:
                policy = build_policy(profile, base_profile)
                state["personalization_policy"] = policy.model_dump()
                state["personalization_reasons"] = dedupe_reasons(policy.explanations)
                state["personalization_context"] = policy.context_text
            except Exception:
                state["personalization_context"] = build_personalization_context(profile, base_profile)
                state["personalization_policy"] = None
                state["personalization_reasons"] = dedupe_reasons([])
            state["personalization_flags"] = build_personalization_flags(profile, base_profile, policy=policy)
            state["personalization_flags"]["personalization_reasons"] = dedupe_reasons(
                state["personalization_flags"].get("personalization_reasons") or state.get("personalization_reasons") or []
            )
            state["personalization_flags"]["personalization_applied"] = compute_personalization_applied(
                state,
                state["personalization_flags"],
            )
        else:
            state["error"] = f"未找到农户档案：{farmer_id}"

    return state


def _resolve_base(
    profile: FarmerProfile, base_id: Optional[str]
) -> tuple[Optional[str], Optional[BaseProfile]]:
    """根据参数和档案选择合适的基地。"""
    resolved_base_id = base_id or profile.active_base_id
    base_profile = None
    if profile.bases:
        if resolved_base_id and resolved_base_id in profile.bases:
            base_profile = profile.bases[resolved_base_id]
        else:
            # 回退使用首个基地
            resolved_base_id = next(iter(profile.bases.keys()))
            base_profile = profile.bases[resolved_base_id]
    return resolved_base_id, base_profile
