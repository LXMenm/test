"""
状态管理模块
定义整个农作物病害诊治系统的状态结构
"""
from typing import TypedDict, List, Optional, Annotated
import operator


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

    # 症状信息（可能有多个症状）
    symptoms: List[str]  # 症状列表

    # 图像信息
    image_path: Optional[str]  # 病害图像路径

    # 诊断结果
    disease_type: Optional[str]  # 病害类型
    disease_confidence: Optional[float]  # 诊断置信度
    disease_description: Optional[str]  # 病害详细描述

    # 治疗方案
    treatment_plan: Optional[str]  # 具体治疗方案
    prevention_advice: Optional[str]  # 预防建议

    # 流程控制
    current_step: str  # 当前执行步骤
    next_action: Optional[str]  # 下一步动作
    is_complete: bool  # 是否完成整个流程

    # 消息历史（用于记录各个智能体的输出）
    messages: Annotated[List[str], operator.add]

    # 历史操作记录（用于防止无限循环）
    history: List[tuple]

    # 错误信息
    error: Optional[str]  # 错误信息（如果有）


def create_initial_state(user_query: str) -> CropDiseaseState:
    """
    创建初始状态

    Args:
        user_query: 用户的初始查询

    Returns:
        初始化的系统状态
    """
    return CropDiseaseState(
        user_query=user_query,
        crop_type=None,
        crop_growth_stage=None,
        symptoms=[],
        image_path=None,
        disease_type=None,
        disease_confidence=None,
        disease_description=None,
        treatment_plan=None,
        prevention_advice=None,
        current_step="start",
        next_action=None,
        is_complete=False,
        messages=[],
        history=[],
        error=None
    )
