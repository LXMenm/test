"""基于个性化约束的治疗方案过滤。"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .profile_models import TreatmentConstraint


def filter_treatment_by_constraints(
    treatment: str, constraints: TreatmentConstraint, flags: Optional[Dict] = None
) -> Tuple[str, List[str]]:
    """
    根据禁用成分、有机偏好和采收临近等约束过滤治疗方案。

    Returns:
        过滤后的治疗方案文本、被过滤的行摘要。
    """
    lines = treatment.splitlines()
    kept: List[str] = []
    dropped: List[str] = []
    banned_lower = [item.lower() for item in constraints.banned_ingredients]

    for line in lines:
        normalized = line.lower()
        if any(banned in normalized for banned in banned_lower):
            dropped.append(line.strip())
            continue
        kept.append(line)

    notes: List[str] = []
    if constraints.prefer_organic:
        notes.append("已根据偏好优先保留低毒/有机或物理防治建议。")
        kept.append("优先选择生物或物理防治措施，避免高残留药剂。")
    if constraints.harvest_window_days:
        notes.append(
            f"采收临近（约{constraints.harvest_window_days}天），请选用安全间隔期短的制剂。"
        )
        kept.append("注意遵循安全间隔期，临近采收时避免使用高残留药剂。")
    if dropped:
        notes.append(f"因禁用成分被移除的方案: {', '.join(dropped)}")

    filtered = "\n".join([line for line in kept if line.strip()]).strip()
    if notes:
        filtered = f"{filtered}\n\n【个性化约束说明】\n" + "\n".join(notes)
    return filtered, dropped
