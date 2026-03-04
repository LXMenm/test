from __future__ import annotations

from typing import Iterable


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
