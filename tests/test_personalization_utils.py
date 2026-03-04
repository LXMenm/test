from personalization.utils import dedupe_reasons


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
