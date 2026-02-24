"""最小回归：校验不同个性化档案会改变处置方案输出。"""
from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app as app_module
from personalization.profile_models import FarmerProfile, TreatmentConstraint
from personalization.profile_store import save_profile

CHEMICAL_KEYWORDS = ["百菌清", "代森锰锌", "嘧菌酯", "戊唑醇", "苯醚甲环唑"]


def _save_profiles() -> tuple[str, str]:
    organic_id = "F9001"
    regular_id = "F9002"

    organic_profile = FarmerProfile(
        farmer_id=organic_id,
        constraints=TreatmentConstraint(
            prefer_organic=True,
            banned_ingredients=["百菌清"],
            harvest_window_days=5,
        ),
    )
    regular_profile = FarmerProfile(
        farmer_id=regular_id,
        constraints=TreatmentConstraint(
            prefer_organic=False,
            banned_ingredients=[],
            harvest_window_days=20,
        ),
    )
    save_profile(organic_profile)
    save_profile(regular_profile)
    return organic_id, regular_id


def _run_once(client: TestClient, farmer_id: str) -> dict:
    image_path = Path("exam.JPG")
    with image_path.open("rb") as f:
        files = {"file": (image_path.name, f, "image/jpeg")}
        data = {
            "crop_type": "番茄",
            "symptoms": "叶片黄化,斑点",
            "farmer_id": farmer_id,
        }
        response = client.post("/api/diagnose-image", files=files, data=data)
    response.raise_for_status()
    return response.json()


def main() -> None:
    organic_id, regular_id = _save_profiles()
    
    class _DummyEngine:
        def diagnose_from_image(self, _):
            return "早疫病", 0.91, {"早疫病": 0.91, "晚疫病": 0.09}

        def diagnose_from_symptoms(self, **kwargs):
            return "早疫病", 0.8, "rule"

    class _DummyGraph:
        def invoke(self, state):
            state["final_disease"] = state.get("final_disease") or "早疫病"
            state["final_confidence"] = 0.91
            state["final_source"] = "image"
            state["diagnosis_model_meta"] = {
                "model_id": "dummy",
                "model_display_name": "dummy",
                "backend": "dummy",
                "resolved_model_path": "dummy",
                "model_fallback_reason": [],
            }
            return state

    app_module.get_diagnosis_engine = lambda **kwargs: _DummyEngine()
    app_module.build_graph = lambda: _DummyGraph()

    client = TestClient(app_module.app)

    organic_resp = _run_once(client, organic_id)
    regular_resp = _run_once(client, regular_id)

    organic_plan = ((organic_resp.get("treatment") or {}).get("plan") or "")
    regular_plan = ((regular_resp.get("treatment") or {}).get("plan") or "")

    assert organic_plan != regular_plan, "有机与常规档案的治疗方案应存在差异"

    for keyword in CHEMICAL_KEYWORDS:
        assert keyword not in organic_plan, f"有机模式治疗方案不应包含化学药剂关键词: {keyword}"

    print("ok: personalization diff verified")


if __name__ == "__main__":
    main()
