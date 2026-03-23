from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from typing import Any, Callable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import knowledge_base.kb_store as kb_store
from knowledge_base.kb_manager import KnowledgeBaseManager
from mysql_models import KBSymptomAliasORM, KBSymptomCandidateDiseaseORM, KBSymptomMapORM
from repositories import kb_repo_mysql
import scripts.migrations.migrate_kb_symptom_map_normalized as migrate_symptom_map_script


def _fixture_diseases() -> dict[str, Any]:
    kb_dir = Path("data/kb")
    return json.loads((kb_dir / "diseases.json").read_text(encoding="utf-8"))


def _fixture_treatments() -> dict[str, Any]:
    kb_dir = Path("data/kb")
    return json.loads((kb_dir / "treatments.json").read_text(encoding="utf-8"))


def _fixture_rules() -> dict[str, Any]:
    kb_dir = Path("data/kb")
    return json.loads((kb_dir / "rules.json").read_text(encoding="utf-8"))


def _symptom_payload() -> dict[str, Any]:
    return {
        "symptom_aliases": {
            "叶片发黄": "发黄",
            "叶子发黄": "发黄",
            "卷叶": "卷曲",
        },
        "symptom_candidates": {
            "发黄": ["黄化曲叶病毒病", "缺素症"],
            "卷曲": ["黄化曲叶病毒病"],
        },
        "symptom_map": {
            "发黄": ["黄化曲叶病毒病", "缺素症"],
            "卷曲": ["黄化曲叶病毒病"],
        },
    }


def _make_session_scope(tmp_path: Path) -> tuple[Any, Callable[[], Any]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'kb_symptom_map.db'}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope


def _create_symptom_tables(engine: Any) -> None:
    KBSymptomMapORM.__table__.create(bind=engine, checkfirst=True)
    KBSymptomAliasORM.__table__.create(bind=engine, checkfirst=True)
    KBSymptomCandidateDiseaseORM.__table__.create(bind=engine, checkfirst=True)


def test_save_symptom_map_mysql_writes_main_and_normalized_child_tables(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_symptom_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)

    payload = _symptom_payload()
    saved = kb_repo_mysql.save_symptom_map_mysql(payload)

    assert saved["symptom_aliases"]["叶片发黄"] == "发黄"
    assert saved["symptom_candidates"]["发黄"] == ["黄化曲叶病毒病", "缺素症"]

    with session_scope() as session:
        main_rows = session.execute(select(KBSymptomMapORM).order_by(KBSymptomMapORM.symptom_key.asc())).scalars().all()
        alias_rows = session.execute(select(KBSymptomAliasORM).order_by(KBSymptomAliasORM.alias.asc())).scalars().all()
        candidate_rows = session.execute(
            select(KBSymptomCandidateDiseaseORM).order_by(
                KBSymptomCandidateDiseaseORM.symptom_key.asc(),
                KBSymptomCandidateDiseaseORM.rank_no.asc(),
            )
        ).scalars().all()

    assert [row.symptom_key for row in main_rows] == ["__payload__", "卷曲", "发黄"]
    assert [(row.symptom_key, row.alias) for row in alias_rows] == [
        ("卷曲", "卷叶"),
        ("发黄", "叶子发黄"),
        ("发黄", "叶片发黄"),
    ]
    assert [(row.symptom_key, row.disease_name, row.rank_no) for row in candidate_rows] == [
        ("卷曲", "黄化曲叶病毒病", 1),
        ("发黄", "黄化曲叶病毒病", 1),
        ("发黄", "缺素症", 2),
    ]


def test_load_symptom_map_mysql_prefers_normalized_child_tables_but_keeps_compatible_shape(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_symptom_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)

    kb_repo_mysql.save_symptom_map_mysql(_symptom_payload())

    with session_scope() as session:
        canonical_row = session.execute(
            select(KBSymptomMapORM).where(KBSymptomMapORM.symptom_key == "发黄")
        ).scalar_one()
        canonical_row.aliases_json = ["旧黄叶别名"]
        canonical_row.disease_candidates_json = ["旧病害"]
        canonical_row.meta_json = {"symptom_map": ["旧病害"]}
        session.commit()

    loaded = kb_repo_mysql.load_symptom_map_mysql()

    assert loaded["symptom_aliases"]["叶片发黄"] == "发黄"
    assert loaded["symptom_candidates"]["发黄"] == ["黄化曲叶病毒病", "缺素症"]
    assert set(loaded.keys()) == {"symptom_aliases", "symptom_candidates", "symptom_map"}


def test_load_symptom_map_mysql_falls_back_to_legacy_json_when_child_tables_are_empty(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_symptom_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)

    payload = _symptom_payload()
    with session_scope() as session:
        session.add(
            KBSymptomMapORM(
                symptom_key="__payload__",
                canonical_symptom="__payload__",
                aliases_json=None,
                disease_candidates_json=None,
                meta_json=payload,
            )
        )
        session.commit()

    loaded = kb_repo_mysql.load_symptom_map_mysql()

    assert loaded == payload


def test_kb_manager_normalize_and_candidate_lookup_do_not_regress(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_symptom_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)
    kb_repo_mysql.save_symptom_map_mysql(_symptom_payload())

    diseases = _fixture_diseases()
    treatments = _fixture_treatments()
    rules = _fixture_rules()

    monkeypatch.setattr(kb_store, "KB_STORE_MODE", "mysql")
    monkeypatch.setattr(
        kb_store,
        "_get_mysql_repo",
        lambda: {
            "load_diseases_mysql": lambda: diseases,
            "save_diseases_mysql": lambda payload: payload,
            "load_treatments_mysql": lambda: treatments,
            "save_treatments_mysql": lambda payload: payload,
            "load_rules_mysql": lambda: rules,
            "save_rules_mysql": lambda payload: payload,
            "load_symptom_map_mysql": kb_repo_mysql.load_symptom_map_mysql,
            "save_symptom_map_mysql": kb_repo_mysql.save_symptom_map_mysql,
        },
    )

    manager = KnowledgeBaseManager()

    assert manager.normalize_symptoms(["叶片发黄", "叶子发黄", "卷叶"]) == ["发黄", "卷曲"]
    assert manager.get_candidate_diseases_from_symptoms(["叶片发黄", "卷叶"]) == ["黄化曲叶病毒病"]


def test_migrate_kb_symptom_map_normalized_script_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    KBSymptomMapORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(migrate_symptom_map_script, "engine", engine)

    payload = _symptom_payload()
    with session_scope() as session:
        session.add(
            KBSymptomMapORM(
                symptom_key="__payload__",
                canonical_symptom="__payload__",
                aliases_json=None,
                disease_candidates_json=None,
                meta_json=payload,
            )
        )
        session.add(
            KBSymptomMapORM(
                symptom_key="发黄",
                canonical_symptom="发黄",
                aliases_json=["叶片发黄", "叶子发黄"],
                disease_candidates_json=["黄化曲叶病毒病", "缺素症"],
                meta_json={"symptom_map": ["黄化曲叶病毒病", "缺素症"]},
            )
        )
        session.add(
            KBSymptomMapORM(
                symptom_key="卷曲",
                canonical_symptom="卷曲",
                aliases_json=["卷叶"],
                disease_candidates_json=["黄化曲叶病毒病"],
                meta_json={"symptom_map": ["黄化曲叶病毒病"]},
            )
        )
        session.commit()

    monkeypatch.setattr(sys, "argv", ["migrate_kb_symptom_map_normalized.py"])

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        migrate_symptom_map_script.main()

    with session_scope() as session:
        alias_count_first = session.execute(select(KBSymptomAliasORM)).scalars().all()
        candidate_count_first = session.execute(select(KBSymptomCandidateDiseaseORM)).scalars().all()

    second_stdout = StringIO()
    with redirect_stdout(second_stdout):
        migrate_symptom_map_script.main()

    with session_scope() as session:
        alias_count_second = session.execute(select(KBSymptomAliasORM)).scalars().all()
        candidate_count_second = session.execute(select(KBSymptomCandidateDiseaseORM)).scalars().all()

    assert len(alias_count_first) == len(alias_count_second) == 3
    assert len(candidate_count_first) == len(candidate_count_second) == 3
    assert "[kb-symptom-map-normalize] canonical_symptoms=2" in first_stdout.getvalue()
    assert "[kb-symptom-map-normalize] aliases=3" in second_stdout.getvalue()
