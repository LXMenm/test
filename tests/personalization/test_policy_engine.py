from personalization.policy_engine import build_policy
from personalization.profile_models import FarmerProfile, TreatmentConstraint


def test_policy_engine_balcony_vs_large_greenhouse():
    profile_a = FarmerProfile(
        farmer_id="PA",
        farm_scale="BALCONY",
        pesticide_access_level="NONE",
        equipment=[],
        cultivation_mode="HYDROPONIC",
        experience_level="NOVICE",
        risk_preference="CONSERVATIVE",
        constraints=TreatmentConstraint(
            prefer_organic=True,
            banned_ingredients=["百菌清"],
            harvest_window_days=3,
        ),
    )
    profile_b = FarmerProfile(
        farmer_id="PB",
        farm_scale="GREENHOUSE_LARGE",
        pesticide_access_level="FULL",
        equipment=["DRONE", "MIST_BLOWER"],
        cultivation_mode="SOIL",
        experience_level="EXPERT",
        risk_preference="BALANCED",
        constraints=TreatmentConstraint(
            prefer_organic=False,
            banned_ingredients=[],
            harvest_window_days=14,
        ),
    )

    policy_a = build_policy(profile_a, base=None)
    policy_b = build_policy(profile_b, base=None)

    assert policy_a.hard_constraints.get("forbid_professional_pesticides") is True
    assert "DRONE" in (policy_a.hard_constraints.get("forbidden_equipment_flows") or [])

    assert policy_b.hard_constraints.get("forbid_professional_pesticides") is False

    # A/B explanations should diverge clearly by scale/equipment/access dimensions.
    joined_a = "\n".join(policy_a.explanations)
    joined_b = "\n".join(policy_b.explanations)

    assert "无法/不便购买专业农药" in joined_a
    assert "未配置无人机设备" in joined_a
    assert "购药能力充足" in joined_b
    assert "已配置无人机设备" in joined_b

    # mandatory rule texts
    assert "水培环境需强调营养液/根区卫生管理，预防根部与环境相关病害" in joined_a
    assert "偏保守风险策略：强调安全间隔、抗性轮换、复查监测" in joined_a
    assert "有机偏好：优先非化学/生物/农艺措施，避免高风险化学成分" in joined_a
    assert "临近采收：强调安全间隔与合规风险提示" in joined_a

    assert len(policy_a.explanations) >= 6
    assert len(policy_b.explanations) >= 6
