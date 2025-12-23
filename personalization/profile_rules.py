"""
个性化规则：根据偏好过滤治疗方案。
"""

from typing import Tuple, Optional, Dict, Any


def filter_treatment_by_constraints(
    treatment: str,
    prevention: str,
    flags: Dict[str, Any],
) -> Tuple[str, str]:
    """
    依据个性化约束过滤治疗/预防文本。
    - organic_only: 添加提醒
    - prohibited_chemicals: 若命中则提示替换
    - harvest_within_days: 加入采收安全期提醒
    """
    notes = []
    if not flags:
        return treatment, prevention

    organic_only = flags.get("organic_only")
    prohibited = flags.get("prohibited_chemicals") or []
    harvest_within_days = flags.get("harvest_within_days")

    filtered_treat = treatment

    # 简单字符串匹配，标记禁用成分
    hits = [chem for chem in prohibited if chem and chem.lower() in treatment.lower()]
    if hits:
        notes.append(f"检测到禁用成分: {', '.join(hits)}，请更换为允许的生物/低残留药剂。")

    if organic_only:
        notes.append("用户要求有机/低残留方案，避免化学合成农药。")

    if harvest_within_days:
        notes.append(f"距离采收 {harvest_within_days} 天内，需选择安全间隔期内的药剂或物理/生物方案。")

    if notes:
        filtered_treat = f"{treatment}\n\n【个性化提醒】\n" + "\n".join(notes)

    return filtered_treat, prevention
