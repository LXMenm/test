from personalization.profile_rules import apply_personalization_to_treatment


def test_prefer_organic_notice_only_still_sets_filtered_true_with_empty_components():
    plan = "建议先清除病叶并加强通风管理。"
    prevention = "保持田间卫生，控制湿度。"
    flags = {
        "prefer_organic": True,
        "banned_ingredients": [],
        "harvest_window_days": None,
    }

    personalized_plan, personalized_prevention, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert personalized_plan
    assert personalized_prevention
    assert outputs["filtered"] is True
    assert outputs["filtered_reasons"]
    assert outputs["filtered_components"] == []


def test_no_constraints_no_intervention_keeps_filtered_fields_empty():
    plan = "建议先清除病叶并加强通风管理。"
    prevention = "保持田间卫生，控制湿度。"
    flags = {
        "prefer_organic": False,
        "banned_ingredients": [],
        "harvest_window_days": None,
    }

    _, _, outputs = apply_personalization_to_treatment(plan, prevention, flags)

    assert outputs["filtered"] is False
    assert outputs["filtered_reasons"] == []
    assert outputs["filtered_components"] == []
