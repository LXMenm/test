from __future__ import annotations

from typing import Iterable, Optional


def evaluate_confidence(
    *,
    top1_confidence: float,
    top2_confidence: Optional[float] = None,
    threshold: float,
    margin_threshold: float,
) -> dict[str, object]:
    reasons: list[str] = []
    if top1_confidence < threshold:
        reasons.append("low_confidence")
    margin = None
    if top2_confidence is not None:
        margin = top1_confidence - top2_confidence
        if margin < margin_threshold:
            reasons.append("low_margin")
    return {
        "need_confirm": bool(reasons),
        "reasons": reasons,
        "margin": margin,
    }


def make_confidence_flags(
    top3: Iterable[tuple[str, float]] | None,
    *,
    fallback_confidence: float = 0.0,
    threshold: float,
    margin_threshold: float,
) -> dict[str, object]:
    top3_list = list(top3 or [])
    top1_conf = float(top3_list[0][1]) if top3_list else float(fallback_confidence)
    top2_conf = float(top3_list[1][1]) if len(top3_list) > 1 else None
    policy = evaluate_confidence(
        top1_confidence=top1_conf,
        top2_confidence=top2_conf,
        threshold=threshold,
        margin_threshold=margin_threshold,
    )
    return {
        "need_confirm": policy["need_confirm"],
        "reasons": policy["reasons"],
        "top1_confidence": top1_conf,
        "top2_confidence": top2_conf,
        "margin": policy["margin"],
    }
