from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app as app_module
from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
)
import personalization.profile_store as profile_store
from repositories import profile_repo_mysql
import scripts.migrations.migrate_farm_bases_normalized as migrate_farm_bases_script


def _profile_payload() -> dict[str, Any]:
    return {
        "farmer_id": "FBASE-NORMALIZED",
        "name": "基地规范化农户",
        "schema_version": "1.2",
        "updated_at": "2026-03-20T00:00:00Z",
        "active_base_id": "B001",
        "confirm_when_low_confidence": True,
        "farm_scale": "MEDIUM",
        "pesticide_access_level": "LIMITED",
        "equipment": ["BACKPACK_SPRAYER"],
        "cultivation_mode": "SOIL",
        "experience_level": "INTERMEDIATE",
        "risk_preference": "BALANCED",
        "constraints": {
            "prefer_organic": True,
            "harvest_window_days": 7,
            "banned_ingredients": ["百菌清"],
        },
        "bases": {
            "B001": {
                "base_id": "B001",
                "internal_base_uid": "base-uid-001",
                "name": "一号棚",
                "location": "山东寿光",
                "province": "山东",
                "facility": "GREENHOUSE",
                "environment": "近期高湿",
                "growth_stage": "FLOWERING",
                "sowing_date": "2026-03-01",
                "risk_tags": ["FLOWERING_FRUITING_SENSITIVE", "HIGH_HUMIDITY"],
                "risk_reasons": ["花果期敏感", "近期湿度高"],
                "risk_items": [
                    {
                        "code": "FLOWERING_FRUITING_SENSITIVE",
                        "label": "花果期敏感",
                        "level": "high",
                        "reason": "开花坐果阶段对药害与湿害更敏感",
                        "source": "growth_stage",
                    },
                    {
                        "code": "HIGH_HUMIDITY",
                        "label": "高湿风险",
                        "level": "warning",
                        "reason": "温室近期高湿，病害压力上升",
                        "source": "structured_weather",
                    },
                ],
            }
        },
    }


def _make_session_scope(tmp_path: Path, filename: str = "farm_bases_normalized.db") -> tuple[Any, Callable[[], Any]]:
    engine = create_engine(f"sqlite:///{tmp_path / filename}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope


def _create_profile_tables(engine: Any) -> None:
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)


def _install_mysql_profile_repo(monkeypatch, tmp_path: Path, session_scope: Callable[[], Any]) -> None:
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile_store, "PROFILE_STORE_MODE", "mysql")
    monkeypatch.setattr(
        profile_store,
        "_get_mysql_repo",
        lambda: {
            "get_profile_mysql": profile_repo_mysql.get_profile,
            "list_profile_ids_mysql": profile_repo_mysql.list_profile_ids,
            "list_all_base_ids_mysql": profile_repo_mysql.list_all_base_ids,
            "save_profile_payload": profile_repo_mysql.save_profile_payload,
            "delete_profile_mysql": profile_repo_mysql.delete_profile,
        },
    )


def test_save_profile_payload_writes_main_and_farm_base_child_tables(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    saved = profile_repo_mysql.save_profile_payload(_profile_payload())

    assert saved["bases"]["B001"]["risk_tags"] == ["FLOWERING_FRUITING_SENSITIVE", "HIGH_HUMIDITY"]
    assert len(saved["bases"]["B001"]["risk_items"]) == 2

    with session_scope() as session:
        base_row = session.execute(select(FarmBaseORM).where(FarmBaseORM.base_id == "B001")).scalar_one()
        risk_tag_rows = session.execute(
            select(FarmBaseRiskTagORM).order_by(FarmBaseRiskTagORM.risk_tag.asc())
        ).scalars().all()
        risk_item_rows = session.execute(select(FarmBaseRiskItemORM).order_by(FarmBaseRiskItemORM.id.asc())).scalars().all()

    assert base_row.risk_tags_json in (None, [])
    assert base_row.risk_items_json in (None, [])
    assert [row.risk_tag for row in risk_tag_rows] == ["FLOWERING_FRUITING_SENSITIVE", "HIGH_HUMIDITY"]
    assert [row.risk_code for row in risk_item_rows] == [None, None]
    assert [row.risk_level for row in risk_item_rows] == [None, None]
    assert [row.risk_message for row in risk_item_rows] == [None, None]


def test_get_profile_prefers_farm_base_child_tables_but_keeps_compatible_shape(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    profile_repo_mysql.save_profile_payload(_profile_payload())

    with session_scope() as session:
        base_row = session.execute(select(FarmBaseORM).where(FarmBaseORM.base_id == "B001")).scalar_one()
        base_row.risk_tags_json = ["LEGACY_TAG"]
        base_row.risk_items_json = [{"code": "LEGACY_ITEM", "label": "旧风险", "level": "low", "reason": "旧原因"}]
        session.commit()

    loaded = profile_repo_mysql.get_profile("FBASE-NORMALIZED")

    assert loaded is not None
    base_payload = loaded["bases"]["B001"]
    assert base_payload["risk_tags"] == ["FLOWERING_FRUITING_SENSITIVE", "HIGH_HUMIDITY"]
    assert [item["code"] for item in base_payload["risk_items"]] == [
        "FLOWERING_FRUITING_SENSITIVE",
        "HIGH_HUMIDITY",
    ]
    assert base_payload["risk_items"][0]["reason"] == "开花坐果阶段对药害与湿害更敏感"


def test_get_profile_falls_back_to_legacy_farm_base_json_when_child_tables_are_empty(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    payload = _profile_payload()
    base_payload = payload["bases"]["B001"]
    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id=payload["farmer_id"],
                name=payload["name"],
                owner_user_id=payload["farmer_id"],
                schema_version="1.2",
                confirm_when_low_confidence=True,
            )
        )
        session.add(
            FarmBaseORM(
                farmer_id=payload["farmer_id"],
                base_id="B001",
                internal_base_uid=base_payload["internal_base_uid"],
                name=base_payload["name"],
                location=base_payload["location"],
                province=base_payload["province"],
                facility=base_payload["facility"],
                environment=base_payload["environment"],
                growth_stage=base_payload["growth_stage"],
                sowing_date=base_payload["sowing_date"],
                risk_tags_json=base_payload["risk_tags"],
                risk_reasons_json=base_payload["risk_reasons"],
                risk_items_json=base_payload["risk_items"],
            )
        )
        session.commit()

    loaded = profile_repo_mysql.get_profile("FBASE-NORMALIZED")

    assert loaded is not None
    assert loaded["bases"]["B001"]["risk_tags"] == ["FLOWERING_FRUITING_SENSITIVE", "HIGH_HUMIDITY"]
    assert [item["code"] for item in loaded["bases"]["B001"]["risk_items"]] == [
        "FLOWERING_FRUITING_SENSITIVE",
        "HIGH_HUMIDITY",
    ]


def test_resolve_profile_and_base_does_not_regress_with_normalized_farm_base_tables(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    _install_mysql_profile_repo(monkeypatch, tmp_path, session_scope)
    profile_repo_mysql.save_profile_payload(_profile_payload())

    profile, base_profile, resolved_base_id = app_module._resolve_profile_and_base("FBASE-NORMALIZED", "B001")

    assert profile is not None
    assert base_profile is not None
    assert resolved_base_id == "B001"
    assert "HIGH_HUMIDITY" in (base_profile.risk_tags or [])
    assert any(item.code == "HIGH_HUMIDITY" for item in (base_profile.risk_items or []))


def test_diagnose_image_personalization_context_does_not_regress_with_normalized_farm_base_tables(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    _install_mysql_profile_repo(monkeypatch, tmp_path, session_scope)
    profile_repo_mysql.save_profile_payload(_profile_payload())

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "cleanup_old_uploads", lambda: None)
    monkeypatch.setattr(app_module, "append_event", lambda event: None)
    monkeypatch.setattr(app_module, "list_trace_events", lambda trace_id: [])
    monkeypatch.setattr(app_module, "emit_node_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "emit_final_event_once", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "Image",
        SimpleNamespace(open=lambda *_args, **_kwargs: SimpleNamespace(verify=lambda: None)),
    )
    monkeypatch.setattr(
        app_module,
        "resolve_model",
        lambda model_id, allow_torch=False: (
            SimpleNamespace(
                model_id="mock-model",
                display_name="Mock Model",
                backend="mock",
                model_path="/models/mock.bin",
            ),
            [],
        ),
    )

    class _DummyImageEngine:
        def diagnose_from_image(self, _):
            return "早疫病", 0.93, {"早疫病": 0.93, "晚疫病": 0.07}

        def diagnose_from_symptoms(self, **kwargs):
            return "早疫病", 0.75, "rule"

        def _get_disease_description(self, disease_type, symptoms):
            return f"{disease_type} - {','.join(symptoms or [])}"

    seen: dict[str, Any] = {}

    class _StaticGraph:
        def invoke(self, state, config=None):
            seen["personalization_context"] = state.get("personalization_context")
            seen["personalization_flags"] = dict(state.get("personalization_flags") or {})
            final_state = dict(state)
            final_state.update(
                {
                    "trace_id": "trace-normalized",
                    "final_disease": "早疫病",
                    "final_confidence": 0.93,
                    "final_source": "image",
                    "personalization_flags": {
                        **dict(state.get("personalization_flags") or {}),
                        "selected_branch": "MID",
                    },
                    "personalization_reasons": ["已加载基地档案上下文"],
                    "treatment_plan": "按基地上下文执行中等规模方案",
                    "prevention_advice": "继续控湿通风",
                    "verification_result": {"passed": True},
                    "verification_passed": True,
                    "verification_risk_level": "low",
                    "verification_issues": [],
                    "verification_summary": "通过",
                    "text_top3": [("早疫病", 0.88)],
                    "fusion_top3": [("早疫病", 0.93)],
                    "diagnosis_evidence": {"final_confidence": 0.93},
                    "modality_conflict_flag": False,
                    "normalized_symptoms": ["叶片黄化"],
                }
            )
            return final_state

    monkeypatch.setattr(app_module, "get_diagnosis_engine", lambda **kwargs: _DummyImageEngine())
    monkeypatch.setattr(app_module, "build_graph", lambda: _StaticGraph())

    client = TestClient(app_module.app)
    response = client.post(
        "/api/diagnose-image",
        files={"file": ("case.jpg", b"fake-jpeg-content", "image/jpeg")},
        data={"crop_type": "番茄", "symptoms": "叶片黄化", "farmer_id": "FBASE-NORMALIZED", "base_id": "B001"},
    )
    response.raise_for_status()
    body = response.json()

    assert "农户ID: FBASE-NORMALIZED" in (seen.get("personalization_context") or "")
    assert "基地ID: B001" in (seen.get("personalization_context") or "")
    assert "HIGH_HUMIDITY" in (seen["personalization_flags"].get("risk_tags") or [])
    assert any(item.get("code") == "HIGH_HUMIDITY" for item in (seen["personalization_flags"].get("risk_items") or []))
    assert "HIGH_HUMIDITY" in (body["meta"].get("risk_tags") or [])
    assert any(item.get("code") == "HIGH_HUMIDITY" for item in (body["meta"].get("risk_items") or []))
    assert body["selected_branch"] == "MID"


def test_migrate_farm_bases_normalized_script_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(migrate_farm_bases_script, "engine", engine)

    base_payload = _profile_payload()["bases"]["B001"]
    with session_scope() as session:
        session.add(
            FarmBaseORM(
                farmer_id="FBASE-NORMALIZED",
                base_id="B001",
                internal_base_uid=base_payload["internal_base_uid"],
                name=base_payload["name"],
                risk_tags_json=base_payload["risk_tags"],
                risk_reasons_json=base_payload["risk_reasons"],
                risk_items_json=base_payload["risk_items"],
            )
        )
        session.commit()

    monkeypatch.setattr(sys, "argv", ["migrate_farm_bases_normalized.py"])

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        migrate_farm_bases_script.main()

    with session_scope() as session:
        risk_tag_rows_first = session.execute(select(FarmBaseRiskTagORM)).scalars().all()
        risk_item_rows_first = session.execute(select(FarmBaseRiskItemORM)).scalars().all()

    second_stdout = StringIO()
    with redirect_stdout(second_stdout):
        migrate_farm_bases_script.main()

    with session_scope() as session:
        risk_tag_rows_second = session.execute(select(FarmBaseRiskTagORM)).scalars().all()
        risk_item_rows_second = session.execute(select(FarmBaseRiskItemORM)).scalars().all()

    assert len(risk_tag_rows_first) == len(risk_tag_rows_second) == 2
    assert len(risk_item_rows_first) == len(risk_item_rows_second) == 2
    assert "[farm-bases-normalize] bases=1" in first_stdout.getvalue()
    assert "[farm-bases-normalize] risk_items=2" in second_stdout.getvalue()
