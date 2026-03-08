from personalization.profile_rules import apply_personalization_to_treatment


def test_scenario_a_prefer_organic_with_specific_component_removal():
    plan = "建议喷施代森锰锌并加强通风。"
    prevention = "保持田间卫生。"
    flags = {
        "prefer_organic": True,
        "banned_ingredients": [],
        "harvest_window_days": None,
    }

    personalized_plan, _, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert outputs["filtered"] is True
    assert "代森锰锌" in outputs["filtered_components"]
    assert any("移除高风险化学农药成分" in reason for reason in outputs["filtered_reasons"])
    assert "请使用替代方案/咨询当地农技" in personalized_plan


def test_scenario_b_prefer_organic_wording_rewrite_without_components():
    plan = "建议使用化学农药时严格遵循标签。"
    prevention = "必要时再考虑化学药剂。"
    flags = {
        "prefer_organic": True,
        "banned_ingredients": [],
        "harvest_window_days": None,
    }

    personalized_plan, personalized_prevention, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert outputs["filtered"] is True
    assert outputs["filtered_components"] == []
    assert any("弱化化学农药措辞" in reason for reason in outputs["filtered_reasons"])
    assert "化学农药" not in personalized_plan
    assert "化学药剂" not in personalized_prevention


def test_scenario_c_policy_evaluated_but_text_unchanged():
    plan = "建议先清除病叶并加强通风管理。"
    prevention = "保持田间卫生，控制湿度。"
    flags = {
        "prefer_organic": True,
        "banned_ingredients": [],
        "harvest_window_days": None,
    }

    _, _, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert outputs["personalization_applied"] is True
    assert outputs["filtered"] is False
    assert outputs["filtered_reasons"] == []
    assert outputs["filtered_components"] == []


def test_scenario_d_banned_ingredient_hit():
    plan = "可使用嘧菌酯或代森锰锌轮换防治。"
    prevention = "保持清园。"
    flags = {
        "prefer_organic": False,
        "banned_ingredients": ["代森锰锌"],
        "harvest_window_days": None,
    }

    _, _, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert outputs["filtered"] is True
    assert "代森锰锌" in outputs["filtered_components"]
    assert any("禁用成分：移除代森锰锌" in reason for reason in outputs["filtered_reasons"])
