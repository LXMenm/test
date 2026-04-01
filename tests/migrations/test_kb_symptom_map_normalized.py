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
import scripts.migrations.backfill_kb_symptom_discriminators as backfill_discriminators_script


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
        "symptom_tiers": {"发黄": "generic", "卷曲": "generic", "节间缩短": "discriminative"},
        "symptom_discriminator_groups": {"节间缩短": ["病毒组"]},
        "follow_up_hints": {"病毒组": ["是否有节间缩短、矮化丛生？"]},
        "negative_cues": {"病毒组": ["叶背白霉"]},
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
    assert {"symptom_aliases", "symptom_candidates", "symptom_map"}.issubset(set(loaded.keys()))
    assert loaded["symptom_tiers"]["节间缩短"] == "discriminative"


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


def test_kb_manager_alias_discriminator_and_followup(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_symptom_tables(engine)
    monkeypatch.setattr(kb_repo_mysql, "get_db_session", session_scope)
    payload = _symptom_payload()
    payload["symptom_aliases"].update({
        "一圈一圈的病斑": "同心轮纹",
        "叶背有白毛": "叶背白霉",
        "像靶子一样": "靶心状病斑",
        "叶背有细网": "叶背结网",
        "叶片一块深一块浅": "明暗相间花叶",
    })
    payload["symptom_candidates"].update({
        "斑点": ["细菌性斑点病", "早疫病", "晚疫病", "叶霉病", "叶斑病", "靶斑病"],
        "同心轮纹": ["早疫病", "靶斑病"],
        "叶背白霉": ["晚疫病", "叶霉病"],
        "叶背橄榄绒霉": ["叶霉病", "早疫病"],
        "黑色小点": ["叶斑病", "早疫病"],
        "叶背结网": ["蜘蛛螨", "早疫病"],
        "节间缩短": ["黄化曲叶病毒病", "花叶病毒病"],
        "明暗相间花叶": ["花叶病毒病", "黄化曲叶病毒病"],
    })
    payload["symptom_map"].update(payload["symptom_candidates"])
    payload["symptom_tiers"].update({
        "同心轮纹": "discriminative",
        "叶背橄榄绒霉": "discriminative",
        "黑色小点": "discriminative",
        "叶背结网": "discriminative",
        "节间缩短": "discriminative",
        "明暗相间花叶": "discriminative",
    })
    kb_repo_mysql.save_symptom_map_mysql(payload)

    diseases = _fixture_diseases()
    treatments = _fixture_treatments()
    rules = _fixture_rules()
    for rule in rules["rules"]:
        if rule.get("disease") == "早疫病":
            rule["symptom_weights"] = {"同心轮纹": 1.4, "黑色小点": 0.1}
        if rule.get("disease") == "靶斑病":
            rule["symptom_weights"] = {"同心轮纹": 0.2}
        if rule.get("disease") == "叶霉病":
            rule["symptom_weights"] = {"叶背橄榄绒霉": 1.6}
        if rule.get("disease") == "叶斑病":
            rule["symptom_weights"] = {"黑色小点": 1.5}
        if rule.get("disease") == "蜘蛛螨":
            rule["symptom_weights"] = {"叶背结网": 1.7}
        if rule.get("disease") == "黄化曲叶病毒病":
            rule["symptom_weights"] = {"节间缩短": 1.6, "明暗相间花叶": 0.2}
        if rule.get("disease") == "花叶病毒病":
            rule["symptom_weights"] = {"节间缩短": 0.2, "明暗相间花叶": 1.6}

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

    assert manager.normalize_symptoms(["一圈一圈的病斑", "叶背有白毛", "像靶子一样", "叶背有细网", "叶片一块深一块浅"]) == [
        "同心轮纹", "叶背白霉", "靶心状病斑", "叶背结网", "明暗相间花叶"
    ]
    assert "早疫病" in manager.get_candidate_diseases_from_symptoms(["同心轮纹"])
    assert "晚疫病" in manager.get_candidate_diseases_from_symptoms(["叶背白霉"])
    assert "叶霉病" in manager.get_candidate_diseases_from_symptoms(["叶背橄榄绒霉"])
    assert "叶斑病" in manager.get_candidate_diseases_from_symptoms(["黑色小点"])
    assert "蜘蛛螨" in manager.get_candidate_diseases_from_symptoms(["叶背结网"])
    assert "黄化曲叶病毒病" in manager.get_candidate_diseases_from_symptoms(["节间缩短"])
    assert "花叶病毒病" in manager.get_candidate_diseases_from_symptoms(["明暗相间花叶"])
    assert "早疫病" in manager.get_candidate_diseases_from_symptoms(["一圈一圈的病斑"])
    assert "晚疫病" in manager.get_candidate_diseases_from_symptoms(["叶背有白毛"])
    assert "蜘蛛螨" in manager.get_candidate_diseases_from_symptoms(["叶背有细网"])
    generic_candidates = manager.get_candidate_diseases_from_symptoms(["斑点"])
    assert len(generic_candidates) >= 4
    narrowed_candidates = manager.get_candidate_diseases_from_symptoms(["同心轮纹", "黑色小点"])
    assert len(narrowed_candidates) <= len(generic_candidates)

    probs_ring = manager.score_diseases_from_text("番茄", ["同心轮纹"])
    assert probs_ring.get("早疫病", 0.0) > probs_ring.get("靶斑病", 0.0)
    probs_leaf_mold = manager.score_diseases_from_text("番茄", ["叶背橄榄绒霉"])
    assert probs_leaf_mold.get("叶霉病", 0.0) > probs_leaf_mold.get("早疫病", 0.0)
    probs_spot = manager.score_diseases_from_text("番茄", ["黑色小点"])
    assert probs_spot.get("叶斑病", 0.0) > probs_spot.get("早疫病", 0.0)
    probs_mite = manager.score_diseases_from_text("番茄", ["叶背有细网"])
    assert probs_mite.get("蜘蛛螨", 0.0) > probs_mite.get("早疫病", 0.0)
    probs_ty = manager.score_diseases_from_text("番茄", ["节间缩短"])
    assert probs_ty.get("黄化曲叶病毒病", 0.0) > probs_ty.get("花叶病毒病", 0.0)
    probs_mosaic = manager.score_diseases_from_text("番茄", ["叶片一块深一块浅"])
    assert probs_mosaic.get("花叶病毒病", 0.0) > probs_mosaic.get("黄化曲叶病毒病", 0.0)

    assert manager.has_discriminative_text_evidence(["斑点", "发黄"]) is False
    assert manager.has_discriminative_text_evidence(["同心轮纹"]) is True

    follow_ups = manager.generate_text_follow_up_questions(
        ["斑点", "叶斑"],
        {"早疫病": 0.35, "靶斑病": 0.34, "晚疫病": 0.31},
    )
    assert any("同心轮纹" in item for item in follow_ups)


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


def test_backfill_kb_symptom_discriminators_script_is_idempotent(monkeypatch) -> None:
    symptom_payload = _symptom_payload()
    rules_payload = {"rules": [{"disease": "早疫病", "symptom_weights": {"同心轮纹": 0.2}}]}

    saved_symptom_payload: dict[str, Any] = {}
    saved_rules_payload: dict[str, Any] = {}
    saved_payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(backfill_discriminators_script, "load_symptom_map", lambda: symptom_payload)
    monkeypatch.setattr(backfill_discriminators_script, "load_rules", lambda: rules_payload)
    monkeypatch.setattr(
        backfill_discriminators_script,
        "save_symptom_map",
        lambda payload: (saved_symptom_payload.update(payload), saved_payloads.append(json.loads(json.dumps(payload)))),
    )
    monkeypatch.setattr(backfill_discriminators_script, "save_rules", lambda payload: saved_rules_payload.update(payload))

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        backfill_discriminators_script.main()
    symptom_payload = saved_payloads[-1]
    rules_payload = saved_rules_payload
    second_stdout = StringIO()
    with redirect_stdout(second_stdout):
        backfill_discriminators_script.main()

    first_stats = json.loads(first_stdout.getvalue().strip().splitlines()[-1])
    second_stats = json.loads(second_stdout.getvalue().strip().splitlines()[-1])
    assert first_stats["canonical_symptom_added"] > 0
    assert first_stats["alias_added"] > 0
    assert first_stats["candidate_added"] > 0
    assert second_stats["canonical_symptom_added"] == 0
    assert second_stats["alias_added"] == 0
    assert second_stats["candidate_added"] == 0
    assert "symptom_tiers" in saved_symptom_payload
    assert "symptom_discriminator_groups" in saved_symptom_payload
    assert saved_symptom_payload["symptom_candidates"]["同心轮纹"] == ["早疫病"]
    assert saved_symptom_payload["symptom_candidates"]["叶背白霉"] == ["晚疫病"]
    assert saved_symptom_payload["symptom_candidates"]["叶背橄榄绒霉"] == ["叶霉病"]
    assert saved_symptom_payload["symptom_candidates"]["黑色小点"] == ["叶斑病"]
    assert saved_symptom_payload["symptom_candidates"]["叶背结网"] == ["蜘蛛螨"]
    assert saved_symptom_payload["symptom_candidates"]["节间缩短"] == ["黄化曲叶病毒病"]
    assert saved_symptom_payload["symptom_candidates"]["明暗相间花叶"] == ["花叶病毒病"]
    assert saved_symptom_payload["symptom_aliases"]["一圈一圈的病斑"] == "同心轮纹"
    assert saved_symptom_payload["symptom_aliases"]["叶背有白毛"] == "叶背白霉"
    assert saved_symptom_payload["symptom_aliases"]["叶背有细网"] == "叶背结网"
    assert saved_rules_payload["rules"][0]["symptom_weights"]["同心轮纹"] >= 1.4
