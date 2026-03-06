from personalization.utils import dedupe_reasons, compute_personalization_applied


def test_dedupe_reasons_normalization_and_stable_order():
    reasons = [
        "未配置无人机设备，因此不会输出无人机喷洒流程",
        "未配置无人机设备，因此不会输出无人机喷洒流程。",
        " 购药能力受限 ",
        "",
        None,
    ]

    assert dedupe_reasons(reasons) == [
        "未配置无人机设备，因此不会输出无人机喷洒流程。",
        "购药能力受限。",
    ]


def test_compute_personalization_applied_case_a_no_farmer_id_false():
    state = {"farmer_id": None, "personalization_context": "规模=SMALL"}
    flags = {"farm_scale": "SMALL", "pesticide_access_level": "LIMITED"}
    assert compute_personalization_applied(state, flags) is False


def test_compute_personalization_applied_case_b_farmer_with_context_true_even_not_filtered():
    state = {"farmer_id": "F0001", "personalization_context": "规模=SMALL；购药能力=LIMITED"}
    flags = {"filtered": False, "filtered_reasons": []}
    assert compute_personalization_applied(state, flags) is True


def test_compute_personalization_applied_case_c_farmer_but_empty_signals_false():
    state = {
        "farmer_id": "F0002",
        "personalization_context": "",
        "personalization_reasons": [],
        "personalization_policy": {},
    }
    flags = {"personalization_reasons": []}
    assert compute_personalization_applied(state, flags) is False
