from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from typing import Any, Callable

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

import knowledge_base.kb_store as kb_store
from knowledge_base.kb_manager import KnowledgeBaseManager
from mysql_models import KBTreatmentActionORM, KBTreatmentIngredientORM, KBTreatmentORM
from repositories import kb_repo_mysql
import scripts.migrations.migrate_kb_treatments_normalized as migrate_treatments_script


def _fixture_payloads() -> dict[str, Any]:
    kb_dir = Path("data/kb")
    return {
        "diseases": json.loads((kb_dir / "diseases.json").read_text(encoding="utf-8")),
        "treatments": json.loads((kb_dir / "treatments.json").read_text(encoding="utf-8")),
        "rules": json.loads((kb_dir / "rules.json").read_text(encoding="utf-8")),
        "symptom_map": json.loads((kb_dir / "symptom_map.json").read_text(encoding="utf-8")),
    }


def _treatments_payload() -> dict[str, Any]:
    fixtures = _fixture_payloads()["treatments"]["treatments"]
    return {
        "treatments": {
            "健康": fixtures["健康"],
            "晚疫病": fixtures["晚疫病"],
        }
    }


def _make_session_scope(tmp_path: Path) -> tuple[Any, Callable[[], Any]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'kb_treatments.db'}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope


def _create_treatment_tables(engine: Any) -> None:
    KBTreatmentORM.__table__.create(bind=engine, checkfirst=True)
    KBTreatmentActionORM.__table__.create(bind=engine, checkfirst=True)
    KBTreatmentIngredientORM.__table__.create(bind=engine, checkfirst=True)


def test_save_treatments_mysql_writes_main_and_normalized_child_tables(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_treatment_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)

    payload = _treatments_payload()
    saved = kb_repo_mysql.save_treatments_mysql(payload)

    late_blight = saved["treatments"]["晚疫病"]
    assert late_blight["actions"]["treatment_plan"]["FAMILY"]
    assert late_blight["ingredients"] == ["氟吡菌胺", "烯酰吗啉", "霜脲氰"]

    with session_scope() as session:
        main_rows = session.execute(select(KBTreatmentORM).order_by(KBTreatmentORM.disease_name.asc())).scalars().all()
        action_rows = session.execute(
            select(KBTreatmentActionORM).where(KBTreatmentActionORM.disease_name == "晚疫病").order_by(
                KBTreatmentActionORM.action_section.asc(),
                KBTreatmentActionORM.seq.asc(),
            )
        ).scalars().all()
        ingredient_rows = session.execute(
            select(KBTreatmentIngredientORM).where(KBTreatmentIngredientORM.disease_name == "晚疫病").order_by(
                KBTreatmentIngredientORM.seq.asc(),
            )
        ).scalars().all()

    assert [row.disease_name for row in main_rows] == ["健康", "晚疫病"]
    assert any(row.action_section == "immediate_actions" for row in action_rows)
    assert any(row.action_section == "treatment_plan.FAMILY" for row in action_rows)
    assert [row.ingredient_name for row in ingredient_rows] == ["氟吡菌胺", "烯酰吗啉", "霜脲氰"]


def test_kb_treatment_weak_fields_not_in_new_schema(tmp_path: Path) -> None:
    engine, _ = _make_session_scope(tmp_path)
    _create_treatment_tables(engine)
    inspector = inspect(engine)

    action_columns = {col["name"] for col in inspector.get_columns("kb_treatment_actions")}
    ingredient_columns = {col["name"] for col in inspector.get_columns("kb_treatment_ingredients")}

    assert "payload_json" not in action_columns
    assert "ingredient_type" not in ingredient_columns
    assert "payload_json" not in ingredient_columns


def test_load_treatments_mysql_prefers_normalized_child_tables_but_keeps_shape(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_treatment_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)

    kb_repo_mysql.save_treatments_mysql(_treatments_payload())

    with session_scope() as session:
        row = session.execute(select(KBTreatmentORM).where(KBTreatmentORM.disease_name == "晚疫病")).scalar_one()
        row.actions_json = {"immediate_actions": ["旧动作"]}
        row.ingredients_json = ["旧成分"]
        session.commit()

    loaded = kb_repo_mysql.load_treatments_mysql()
    late_blight = loaded["treatments"]["晚疫病"]

    assert late_blight["actions"]["immediate_actions"]
    assert "旧动作" not in late_blight["actions"]["immediate_actions"]
    assert late_blight["ingredients"] == ["氟吡菌胺", "烯酰吗啉", "霜脲氰"]


def test_kb_manager_get_treatment_plan_actions_and_ingredients_do_not_regress(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_treatment_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)
    kb_repo_mysql.save_treatments_mysql(_treatments_payload())

    fixtures = _fixture_payloads()
    monkeypatch.setattr(kb_store, "KB_STORE_MODE", "mysql")
    monkeypatch.setattr(
        kb_store,
        "_get_mysql_repo",
        lambda: {
            "load_diseases_mysql": lambda: fixtures["diseases"],
            "save_diseases_mysql": lambda payload: payload,
            "load_treatments_mysql": kb_repo_mysql.load_treatments_mysql,
            "save_treatments_mysql": kb_repo_mysql.save_treatments_mysql,
            "load_rules_mysql": lambda: fixtures["rules"],
            "save_rules_mysql": lambda payload: payload,
            "load_symptom_map_mysql": lambda: fixtures["symptom_map"],
            "save_symptom_map_mysql": lambda payload: payload,
        },
    )

    manager = KnowledgeBaseManager()
    plan = manager.get_treatment_plan("晚疫病")

    assert plan["treatment"]
    assert plan["prevention"]
    assert plan["actions"]["immediate_actions"]
    assert plan["actions"]["treatment_plan"]["FAMILY"]
    assert plan["actions"]["treatment_plan"]["MID"]
    assert plan["actions"]["treatment_plan"]["ENTERPRISE"]
    assert plan["ingredients"] == ["氟吡菌胺", "烯酰吗啉", "霜脲氰"]


def test_migrate_kb_treatments_normalized_script_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    KBTreatmentORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(migrate_treatments_script, "engine", engine)

    late_blight = _treatments_payload()["treatments"]["晚疫病"]
    with session_scope() as session:
        session.add(
            KBTreatmentORM(
                disease_name="晚疫病",
                treatment=late_blight["treatment"],
                prevention=late_blight["prevention"],
                actions_json=late_blight["actions"],
                ingredients_json=late_blight["ingredients"],
                meta_json=late_blight,
            )
        )
        session.commit()

    monkeypatch.setattr(sys, "argv", ["migrate_kb_treatments_normalized.py"])

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        migrate_treatments_script.main()

    with session_scope() as session:
        action_rows_first = session.execute(select(KBTreatmentActionORM)).scalars().all()
        ingredient_rows_first = session.execute(select(KBTreatmentIngredientORM)).scalars().all()

    second_stdout = StringIO()
    with redirect_stdout(second_stdout):
        migrate_treatments_script.main()

    with session_scope() as session:
        action_rows_second = session.execute(select(KBTreatmentActionORM)).scalars().all()
        ingredient_rows_second = session.execute(select(KBTreatmentIngredientORM)).scalars().all()

    assert len(action_rows_first) == len(action_rows_second)
    assert len(ingredient_rows_first) == len(ingredient_rows_second) == 3
    assert "[kb-treatments-normalize] diseases=1" in first_stdout.getvalue()
    assert "[kb-treatments-normalize] ingredient_rows=3" in second_stdout.getvalue()
