"""个性化策略引擎：将档案转换为结构化策略与可解释理由。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .profile_models import BaseProfile, FarmerProfile
from .utils import dedupe_reasons


class PersonalizationPolicy(BaseModel):
    farm_scale: str
    pesticide_access_level: str
    cultivation_mode: str
    experience_level: str
    risk_preference: str
    equipment: List[str] = Field(default_factory=list)
    hard_constraints: Dict[str, Any] = Field(default_factory=dict)
    soft_preferences: Dict[str, Any] = Field(default_factory=dict)
    explanations: List[str] = Field(default_factory=list)
    context_text: str



def _detail_level_from_experience(experience_level: str) -> str:
    mapping = {
        "NOVICE": "step_by_step",
        "INTERMEDIATE": "actionable",
        "EXPERT": "concise_professional",
    }
    return mapping.get(experience_level, "actionable")



def build_policy(profile: FarmerProfile, base: Optional[BaseProfile] = None) -> PersonalizationPolicy:
    constraints = profile.constraints
    equipment = [str(item) for item in (profile.equipment or [])]

    hard_constraints: Dict[str, Any] = {
        "banned_ingredients": list(constraints.banned_ingredients or []),
        "harvest_window_days": constraints.harvest_window_days,
        "forbidden_equipment_flows": [],
        "forbid_professional_pesticides": False,
    }

    soft_preferences: Dict[str, Any] = {
        "prefer_organic": bool(constraints.prefer_organic),
        "detail_level": _detail_level_from_experience(profile.experience_level),
    }

    explanations: List[str] = []

    # 1) 规模/购药能力 -> 专业农药限制
    if profile.farm_scale == "BALCONY" or profile.pesticide_access_level == "NONE":
        hard_constraints["forbid_professional_pesticides"] = True
        explanations.append("无法/不便购买专业农药，优先家庭可执行措施（农艺/物理/低毒生物）。")
    elif profile.pesticide_access_level == "LIMITED":
        explanations.append("购药能力受限：优先可获得且操作简化的方案，避免高度依赖专业渠道。")
    else:
        explanations.append("购药能力充足：可在合规前提下提供更完整的药剂与轮换策略。")

    # 2) 设备流限制
    if "DRONE" not in equipment:
        hard_constraints["forbidden_equipment_flows"].append("DRONE")
        explanations.append("未配置无人机设备，因此不会输出无人机喷洒流程。")
    else:
        explanations.append("已配置无人机设备：可提供大面积高效率喷洒流程。")

    if "MIST_BLOWER" not in equipment and profile.farm_scale in {"LARGE", "GREENHOUSE_LARGE"}:
        hard_constraints["forbidden_equipment_flows"].append("MIST_BLOWER")
        explanations.append("规模较大但未配置弥雾设备，流程将偏向分区喷施与人工可执行路径。")

    # 3) 栽培模式
    if profile.cultivation_mode == "HYDROPONIC":
        explanations.append("水培环境需强调营养液/根区卫生管理，预防根部与环境相关病害。")
    elif profile.cultivation_mode == "SUBSTRATE":
        explanations.append("基质栽培需关注基质湿度、消毒与盐分管理，降低病害压力。")
    else:
        explanations.append("土培场景强调土壤通气、轮作与田间卫生管理。")

    # 4) 风险偏好
    if profile.risk_preference == "CONSERVATIVE":
        explanations.append("偏保守风险策略：强调安全间隔、抗性轮换、复查监测。")
    elif profile.risk_preference == "AGGRESSIVE":
        explanations.append("偏积极风险策略：在合规前提下追求快速压制，但仍保留复查节点。")
    else:
        explanations.append("平衡风险策略：兼顾见效速度与残留/抗性控制。")

    # 5) 有机偏好
    if constraints.prefer_organic:
        explanations.append("有机偏好：优先非化学/生物/农艺措施，避免高风险化学成分。")

    # 6) 采收窗口
    if constraints.harvest_window_days is not None and constraints.harvest_window_days <= 7:
        explanations.append("临近采收：强调安全间隔与合规风险提示。")

    # 7) 经验水平
    if profile.experience_level == "NOVICE":
        explanations.append("经验较少：输出更细化步骤、频次与观察指标，降低执行门槛。")
    elif profile.experience_level == "EXPERT":
        explanations.append("经验丰富：可使用更专业术语与策略分支，减少基础解释。")

    # 8) 基地补充
    if base and base.facility:
        explanations.append(f"基地设施条件：{base.facility}，策略将适配对应环境管理要点。")

    # 确保至少 6 条解释
    if len(explanations) < 6:
        explanations.extend([
            "方案将结合档案约束进行可执行性校验。",
            "建议执行后按症状变化进行复诊与参数微调。",
        ])

    context_text = (
        f"规模={profile.farm_scale}；购药能力={profile.pesticide_access_level}；"
        f"栽培模式={profile.cultivation_mode}；经验={profile.experience_level}；"
        f"风险偏好={profile.risk_preference}；设备={','.join(equipment) if equipment else '无'}"
    )

    return PersonalizationPolicy(
        farm_scale=profile.farm_scale,
        pesticide_access_level=profile.pesticide_access_level,
        cultivation_mode=profile.cultivation_mode,
        experience_level=profile.experience_level,
        risk_preference=profile.risk_preference,
        equipment=equipment,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        explanations=dedupe_reasons(explanations),
        context_text=context_text,
    )
