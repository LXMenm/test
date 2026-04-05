from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import agents as agents_module
import app as app_module
from fastapi.testclient import TestClient
from state import create_initial_state
from workflow import build_graph


class _DummyEngine:
    def diagnose_from_image(self, _):
        return "蜘蛛螨", 0.97, {"蜘蛛螨": 0.97, "早疫病": 0.03}

    def diagnose_from_symptoms(self, **kwargs):
        return "非番茄作物", 0.0, "本系统仅支持番茄病害诊断"

    def _get_disease_description(self, disease_type, symptoms):
        return f"{disease_type} - {','.join(symptoms or [])}"


def _mock_call_llm(prompt: str, system_prompt: str, temperature: float = 0.3):
    if "输出JSON schema" in prompt and '"treatment_plan"' in prompt:
        payload = {
            "overview": "蜘蛛螨处置",
            "immediate_actions": ["去除重度受害叶片"],
            "treatment_plan": {
                "BALCONY": ["阳台场景先进行局部处理"],
                "SMALL_MEDIUM": ["常规喷施并复查"],
                "LARGE_MECHANIZED": ["规模化执行并复查"],
            },
            "prevention_plan": ["加强通风", "降低叶面湿度"],
            "resistance_management": ["轮换作用机制"],
            "safety_notes": ["遵守标签与安全间隔"],
            "follow_up": ["48小时复查"],
            "personalization_reasons": ["图像高置信度，优先直接处置"],
            "follow_up_questions": [],
        }
        return json.dumps(payload, ensure_ascii=False)

    if "请输出1-2条与位置/设施/偏好有关的诊断风险提醒" in prompt:
        return "温室注意通风降湿。"

    return json.dumps({"growth_stage": None, "symptoms": ["叶片失绿", "有斑点"]}, ensure_ascii=False)


class _MinimalKB:
    symptom_tiers = {}
    symptom_candidates = {}

    @staticmethod
    def normalize_symptoms(symptoms):
        return [str(item).strip() for item in (symptoms or []) if str(item).strip()]

    @staticmethod
    def has_effective_text_evidence(symptoms, **_kwargs):
        return bool(symptoms)

    @staticmethod
    def has_discriminative_text_evidence(_symptoms):
        return False

    @staticmethod
    def get_candidate_diseases_from_symptoms(_symptoms):
        return []

    @staticmethod
    def generate_text_follow_up_questions(_symptoms, text_probs=None):
        _ = text_probs
        return []


def test_first_diagnosis_has_image_path_and_no_confirm(monkeypatch, tmp_path):
    image = tmp_path / "leaf.jpg"
    image.write_bytes(b"fake")

    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agents_module, "get_diagnosis_engine", lambda **kwargs: _DummyEngine())
    monkeypatch.setattr(agents_module, "call_llm", _mock_call_llm)

    state = create_initial_state(f"作物类型：番茄，图片路径：{image}")
    graph = build_graph()
    final_state = graph.invoke(state, config={"recursion_limit": 80})

    diagnosis_events = [e for e in final_state.get("trace_events", []) if e.get("agent") == "diagnosis"]
    assert diagnosis_events, "缺少 diagnosis trace"
    assert diagnosis_events[0].get("inputs", {}).get("image_path")

    steps = [e.get("step") for e in final_state.get("trace_events", [])]
    assert "kb_retrieval_complete" in steps
    assert "treatment_complete" in steps

    flags = final_state.get("personalization_flags") or {}
    assert flags.get("need_confirm") is False

    decisions = [e.get("decision", {}) for e in final_state.get("trace_events", []) if e.get("agent") == "supervisor"]
    actions = [d.get("next_action") for d in decisions if isinstance(d, dict)]
    assert "reception" not in actions[1:], "不应在首次高置信诊断后自动进入二次确认链路"


def test_parse_input_image_path_is_visible_at_supervisor_start(monkeypatch, tmp_path):
    image = tmp_path / "start-visible.jpg"
    image.write_bytes(b"fake")
    state = create_initial_state("作物类型：番茄", image_path=str(image), trace_id="trace-start-visible")

    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    out = agents_module.supervisor_agent(state)
    supervisor_events = [e for e in out.get("trace_events", []) if e.get("agent") == "supervisor"]
    assert supervisor_events, "缺少 supervisor trace"
    first_inputs = supervisor_events[0].get("inputs", {})
    assert first_inputs.get("image_path") == str(image)


def test_graph_initial_state_carries_image_path_from_request(monkeypatch, tmp_path):
    saved = tmp_path / "request-image.jpg"
    saved.write_bytes(b"fake")
    captured = {}

    class _FakeGraph:
        def invoke(self, initial_state, config=None):
            captured["initial_state"] = dict(initial_state)
            captured["config"] = dict(config or {})
            final_state = dict(initial_state)
            final_state.update(
                {
                    "trace_id": initial_state.get("trace_id"),
                    "final_disease": "早疫病",
                    "final_confidence": 0.91,
                    "final_source": "fusion",
                    "personalization_flags": {},
                    "follow_up_questions": [],
                    "profile_follow_up_questions": [],
                    "diagnosis_follow_up_questions": [],
                    "workflow_degraded": False,
                    "degraded_reason": None,
                    "verification_result": None,
                    "verification_passed": None,
                    "verification_risk_level": None,
                    "verification_issues": [],
                    "verification_summary": None,
                    "debug_diagnosis": {},
                }
            )
            return final_state

    async def _fake_save_uploaded_image(*_args, **_kwargs):
        return "request-image.jpg", saved

    monkeypatch.setattr(app_module, "_save_uploaded_image", _fake_save_uploaded_image)
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (SimpleNamespace(model_path="/tmp/mock.bin", backend="mock", model_id="mock", display_name="mock"), []),
    )
    monkeypatch.setattr(
        app_module,
        "get_diagnosis_engine",
        lambda **kwargs: SimpleNamespace(diagnose_from_image=lambda _path: ("早疫病", 0.91, {"早疫病": 0.91, "晚疫病": 0.09})),
    )
    monkeypatch.setattr(app_module, "build_graph", lambda: _FakeGraph())
    monkeypatch.setattr(app_module, "_build_degraded_treatment", lambda *_args, **_kwargs: (None, {}))

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄"},
    )
    assert resp.status_code == 200
    assert captured.get("initial_state"), "graph.invoke 未被调用"
    assert captured["initial_state"].get("image_path") == str(saved)


def test_reception_query_image_path_parse_is_fallback_not_primary(monkeypatch, tmp_path):
    primary = tmp_path / "primary.jpg"
    query_path = tmp_path / "query.jpg"
    primary.write_bytes(b"primary")
    query_path.write_bytes(b"query")

    monkeypatch.setattr(
        agents_module,
        "call_llm",
        lambda *_args, **_kwargs: json.dumps({"growth_stage": None, "symptoms": []}, ensure_ascii=False),
    )
    monkeypatch.setattr(agents_module, "append_trace_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agents_module, "kb_manager", _MinimalKB())

    state = create_initial_state(f"图片路径：{query_path}", image_path=str(primary))
    out = agents_module.reception_agent(state)
    assert out.get("image_path") == str(primary)
