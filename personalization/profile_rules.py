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


CHEMICAL_KEYWORDS = ["百菌清", "代森锰锌", "嘧菌酯", "戊唑醇", "苯醚甲环唑"]


def apply_personalization_to_treatment(
    plan: str,
    prevention: str,
    flags: Optional[Dict] = None,
) -> Tuple[str, str, Dict[str, object]]:
    """将个性化约束应用到治疗方案文案。"""
    flags = flags or {}
    reasons: List[str] = []
    filtered_components: List[str] = []
    prefer_organic = bool(flags.get("prefer_organic"))
    banned_ingredients = [str(item).strip() for item in (flags.get("banned_ingredients") or []) if str(item).strip()]
    harvest_window_days = flags.get("harvest_window_days")

    lines = [*(plan or "").splitlines(), *(prevention or "").splitlines()]
    plan_lines: List[str] = []
    prevention_lines: List[str] = []

    for index, line in enumerate(lines):
        normalized = line.lower()
        hit_components: List[str] = []
        if prefer_organic:
            hit_components.extend([kw for kw in CHEMICAL_KEYWORDS if kw and kw.lower() in normalized])
        hit_components.extend([kw for kw in banned_ingredients if kw and kw.lower() in normalized])

        if hit_components:
            filtered_components.extend(hit_components)
            replacement = "请使用替代方案/咨询当地农技"
            if index < len((plan or "").splitlines()):
                plan_lines.append(replacement)
            else:
                prevention_lines.append(replacement)
            continue

        if index < len((plan or "").splitlines()):
            plan_lines.append(line)
        else:
            prevention_lines.append(line)

    if prefer_organic:
        reasons.append("偏好有机/低残留：过滤化学农药")
    if banned_ingredients:
        reasons.append(f"禁用成分：{', '.join(sorted(set(banned_ingredients)))}")

    top_notice = "⚠️ 临近采收，优先低残留/物理措施，谨慎用药"
    try:
        harvest_days_value = int(harvest_window_days)
    except Exception:
        harvest_days_value = None
    if harvest_days_value is not None and harvest_days_value <= 7:
        if top_notice not in plan_lines:
            plan_lines.insert(0, top_notice)
        reasons.append("距采收较近：降低残留风险")

    filtered_components = sorted(set(filtered_components))
    filtered = bool(filtered_components)
    outputs: Dict[str, object] = {
        "personalization_applied": bool(reasons or filtered),
        "filtered": filtered,
        "filtered_reasons": reasons,
        "filtered_components": filtered_components,
    }
    return "\n".join([line for line in plan_lines if line.strip()]).strip(), "\n".join(
        [line for line in prevention_lines if line.strip()]
    ).strip(), outputs
