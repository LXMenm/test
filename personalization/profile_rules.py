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
CHEMICAL_WORDING_REWRITES = {
    "化学农药": "登记药剂或低残留制剂",
    "化学药剂": "登记药剂或低残留制剂",
    "化学用药": "低残留用药",
}


def normalize_filter_outputs(outputs: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """规范过滤字段语义，避免 filtered 与 reasons/components 自相矛盾。

    语义约定：
    - filtered: 仅在最终 treatment/prevention 文本确实发生个性化后处理变更时为 True。
    - filtered_reasons: 发生变更的原因。
    - filtered_components: 被删除/替换/弱化命中的具体成分或关键词（可为空）。
    - filtered_actions: 变更动作类型（remove_component/rewrite_wording/harvest_warning/replace_component）。
    """
    outputs = dict(outputs or {})
    filtered = bool(outputs.get("filtered"))
    reasons = [str(item).strip() for item in (outputs.get("filtered_reasons") or []) if str(item).strip()]
    components = [str(item).strip() for item in (outputs.get("filtered_components") or []) if str(item).strip()]
    actions = [str(item).strip() for item in (outputs.get("filtered_actions") or []) if str(item).strip()]

    reasons = sorted(set(reasons))
    components = sorted(set(components))
    actions = sorted(set(actions))

    if not filtered:
        reasons = []
        components = []
        actions = []
    elif filtered and not reasons:
        reasons = ["个性化后处理：文本已调整"]

    outputs["filtered"] = filtered
    outputs["filtered_reasons"] = reasons
    outputs["filtered_components"] = components
    outputs["filtered_actions"] = actions
    outputs["personalization_applied"] = bool(outputs.get("personalization_applied"))
    return outputs


def _normalize_text_for_compare(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def apply_personalization_to_treatment(
    plan: str,
    prevention: str,
    flags: Optional[Dict] = None,
) -> Tuple[str, str, Dict[str, object]]:
    """将个性化约束应用到治疗方案文案。"""
    flags = flags or {}
    prefer_organic = bool(flags.get("prefer_organic"))
    banned_ingredients = [str(item).strip() for item in (flags.get("banned_ingredients") or []) if str(item).strip()]
    harvest_window_days = flags.get("harvest_window_days")

    reasons: List[str] = []
    filtered_components: List[str] = []
    filtered_actions: List[str] = []

    plan_lines: List[str] = []
    prevention_lines: List[str] = []
    original_plan_lines = (plan or "").splitlines()
    original_prevention_lines = (prevention or "").splitlines()
    all_lines = [*original_plan_lines, *original_prevention_lines]

    banned_lower_map = {item.lower(): item for item in banned_ingredients}
    original_plan_len = len(original_plan_lines)

    for index, line in enumerate(all_lines):
        line_out = line
        normalized = line.lower()

        banned_hits = sorted({origin for lower, origin in banned_lower_map.items() if lower in normalized})
        chemical_hits = sorted({kw for kw in CHEMICAL_KEYWORDS if kw and kw.lower() in normalized}) if prefer_organic else []
        removable_hits = sorted(set([*banned_hits, *chemical_hits]))

        if removable_hits:
            filtered_components.extend(removable_hits)
            if banned_hits:
                reasons.extend([f"禁用成分：移除{item}" for item in banned_hits])
            if chemical_hits:
                reasons.append("有机偏好：移除高风险化学农药成分")
            filtered_actions.append("remove_component")
            line_out = "请使用替代方案/咨询当地农技"
        elif prefer_organic:
            rewrote = False
            for src, dst in CHEMICAL_WORDING_REWRITES.items():
                if src in line_out:
                    line_out = line_out.replace(src, dst)
                    rewrote = True
            if rewrote:
                reasons.append("有机偏好：弱化化学农药措辞")
                filtered_actions.append("rewrite_wording")

        if index < original_plan_len:
            plan_lines.append(line_out)
        else:
            prevention_lines.append(line_out)

    top_notice = "⚠️ 临近采收，优先低残留/物理措施，谨慎用药"
    try:
        harvest_days_value = int(harvest_window_days)
    except Exception:
        harvest_days_value = None
    if harvest_days_value is not None and harvest_days_value <= 7 and top_notice not in plan_lines:
        plan_lines.insert(0, top_notice)
        reasons.append("采收窗口限制：补充低残留与安全间隔提示")
        filtered_actions.append("harvest_warning")

    new_plan = "\n".join([line for line in plan_lines if line.strip()]).strip()
    new_prevention = "\n".join([line for line in prevention_lines if line.strip()]).strip()
    original_plan = "\n".join([line for line in original_plan_lines if line.strip()]).strip()
    original_prevention = "\n".join([line for line in original_prevention_lines if line.strip()]).strip()

    text_changed = (
        _normalize_text_for_compare(new_plan) != _normalize_text_for_compare(original_plan)
        or _normalize_text_for_compare(new_prevention) != _normalize_text_for_compare(original_prevention)
    )

    outputs: Dict[str, object] = {
        "personalization_applied": bool(prefer_organic or banned_ingredients or harvest_window_days is not None),
        "filtered": text_changed,
        "filtered_reasons": reasons,
        "filtered_components": filtered_components,
        "filtered_actions": filtered_actions,
    }
    outputs = normalize_filter_outputs(outputs)
    return new_plan, new_prevention, outputs
