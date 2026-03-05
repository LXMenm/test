from __future__ import annotations

from typing import Any, Iterable, Mapping


def _normalize_reason(reason: str) -> str:
    text = reason.strip()
    if not text:
        return ""
    text = " ".join(text.split())
    text = text.rstrip("。.").strip()
    if not text:
        return ""
    return f"{text}。"


def dedupe_reasons(reasons: Iterable[str | None]) -> list[str]:
    """Stable de-dup for display-layer reasons with light normalization."""
    seen: set[str] = set()
    result: list[str] = []
    for item in reasons:
        if item is None:
            continue
        normalized = _normalize_reason(str(item))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _has_non_empty_mapping(value: Any) -> bool:
    return isinstance(value, Mapping) and any(v not in (None, "", [], {}, ()) for v in value.values())


def compute_personalization_applied(
    state: Mapping[str, Any] | None,
    flags: Mapping[str, Any] | None,
) -> bool:
    """Determine whether personalization actually participated in decision/generation."""
    state = state or {}
    flags = flags or {}

    farmer_id = str(state.get("farmer_id") or flags.get("farmer_id") or "").strip()
    if not farmer_id:
        return False

    context_text = str(state.get("personalization_context") or flags.get("personalization_context") or "").strip()
    if context_text:
        return True

    merged_reasons = dedupe_reasons([
        *(state.get("personalization_reasons") or []),
        *(flags.get("personalization_reasons") or []),
    ])
    if merged_reasons:
        return True

    policy = state.get("personalization_policy")
    if _has_non_empty_mapping(policy):
        return True

    core_flag_fields = ["farm_scale", "pesticide_access_level", "cultivation_mode", "equipment", "experience_level", "risk_preference"]
    if any(flags.get(key) not in (None, "", [], {}, ()) for key in core_flag_fields):
        return True

    return False
