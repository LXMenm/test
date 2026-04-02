from __future__ import annotations

import agents as agents_module
from state import create_initial_state


def _base_state() -> dict:
    state = create_initial_state("作物类型：番茄")
    state["fusion_top3"] = [("早疫病", 0.42), ("叶斑病", 0.39), ("细菌性斑点病", 0.19)]
    state["text_top3"] = [("早疫病", 0.45), ("叶斑病", 0.4), ("细菌性斑点病", 0.15)]
    return state


def test_image_mode_prefers_photo_guidance():
    state = _base_state()
    state["supplement_mode"] = "image_only"
    state["image_reliable"] = False
    state["text_reliable"] = True
    flags = {"confirm_ui_mode": "image", "fallback_reason": ["low_confidence"]}

    follow_ups = agents_module._build_follow_up_questions(["叶片有病斑"], flags, state)

    photo_hits = [q for q in follow_ups if any(k in q for k in ["补拍", "清晰", "逆光", "特写", "画面主体"])]
    assert len(photo_hits) >= 2


def test_text_mode_prefers_virus_discriminative_questions():
    state = _base_state()
    state["fusion_top3"] = [("黄化曲叶病毒病", 0.46), ("花叶病毒病", 0.44), ("早疫病", 0.1)]
    state["supplement_mode"] = "text_only"
    state["image_reliable"] = True
    state["text_reliable"] = False
    flags = {"confirm_ui_mode": "text", "fallback_reason": ["low_confidence", "text_weak"]}

    follow_ups = agents_module._build_follow_up_questions(["叶片卷曲", "花叶"], flags, state)

    assert any("黄化上卷" in q or "花叶斑驳" in q for q in follow_ups)
    assert any("节间缩短" in q for q in follow_ups)
    assert any("蕨叶样" in q or "线叶样" in q for q in follow_ups)


def test_image_and_text_mode_contains_photo_and_symptom_questions():
    state = _base_state()
    state["supplement_mode"] = "image_and_text"
    state["image_reliable"] = False
    state["text_reliable"] = False
    flags = {"confirm_ui_mode": "image_and_text", "fallback_reason": ["low_confidence", "both_weak"]}

    follow_ups = agents_module._build_follow_up_questions(["病斑扩展"], flags, state)

    assert any(any(k in q for k in ["补拍", "清晰", "特写"]) for q in follow_ups)
    assert any(any(k in q for k in ["同心轮纹", "黑色小点", "白色霉层", "水渍状"]) for q in follow_ups)


def test_low_margin_prioritizes_discriminative_leaf_spot_questions():
    state = _base_state()
    state["supplement_mode"] = "text_only"
    state["image_reliable"] = True
    state["text_reliable"] = True
    flags = {"confirm_ui_mode": "text", "fallback_reason": ["low_margin"]}

    follow_ups = agents_module._build_follow_up_questions(["病斑"], flags, state)

    assert any(any(k in q for k in ["同心轮纹", "黑色小点", "白色霉层", "橄榄色绒霉", "水渍状"]) for q in follow_ups)


def test_weak_image_text_conflict_with_image_mode_still_prefers_photo_guidance():
    state = _base_state()
    state["supplement_mode"] = "image_only"
    state["image_reliable"] = False
    state["text_reliable"] = True
    state["fusion_case"] = "weak_image_text_conflict"
    flags = {"confirm_ui_mode": "image", "fallback_reason": ["image_text_conflict"]}

    follow_ups = agents_module._build_follow_up_questions(["叶背有斑"], flags, state)

    photo_hits = [q for q in follow_ups if any(k in q for k in ["补拍", "清晰", "逆光", "特写", "画面主体"])]
    assert len(photo_hits) >= 2
