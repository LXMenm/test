from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
)
from repositories import profile_repo_mysql
import scripts.migrations.migrate_constraints_json_to_normalized as constraints_backfill_script


def _make_session_scope(tmp_path: Path, filename: str = "constraints_backfill.db") -> tuple[Any, Callable[[], Any]]:
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


def _create_tables(engine: Any) -> None:
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)


def test_constraints_backfill_fills_json_only_profile_and_reduces_json_only_count(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_tables(engine)

    monkeypatch.setattr(constraints_backfill_script, "engine", engine)
    monkeypatch.setattr(constraints_backfill_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F-CJ-ONLY",
                owner_user_id="F-CJ-ONLY",
                role_type="FARMER",
                constraints_json={
                    "prefer_organic": True,
                    "harvest_window_days": 9,
                    "banned_ingredients": ["百菌清", "代森锰锌"],
                },
                prefer_organic=False,
                harvest_window_days=None,
            )
        )
        session.commit()

    with session_scope() as session:
        before = constraints_backfill_script.audit_constraints_json_dependency(session)
    assert before["constraints_json_only"] == 1

    stats = constraints_backfill_script.backfill_constraints_json_to_normalized()

    assert stats["constraints_profiles"] == 1
    assert stats["prefer_organic_backfilled"] == 1
    assert stats["harvest_window_backfilled"] == 1
    assert stats["banned_ingredients_inserted"] == 2
    assert stats["conflict_profiles"] == 0
    assert stats["invalid_profiles"] == 0

    with session_scope() as session:
        profile = session.execute(
            select(FarmerProfileORM).where(FarmerProfileORM.farmer_id == "F-CJ-ONLY")
        ).scalar_one()
        ingredient_rows = session.execute(
            select(FarmerProfileBannedIngredientORM)
            .where(FarmerProfileBannedIngredientORM.farmer_id == "F-CJ-ONLY")
            .order_by(FarmerProfileBannedIngredientORM.seq.asc())
        ).scalars().all()
        after = constraints_backfill_script.audit_constraints_json_dependency(session)

    assert profile.prefer_organic is True
    assert profile.harvest_window_days == 9
    assert [row.ingredient_name for row in ingredient_rows] == ["百菌清", "代森锰锌"]
    assert after["constraints_json_only"] == 0


def test_constraints_backfill_is_idempotent_and_preserves_existing_normalized_data(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_tables(engine)

    monkeypatch.setattr(constraints_backfill_script, "engine", engine)
    monkeypatch.setattr(constraints_backfill_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F-CJ-DUAL",
                owner_user_id="F-CJ-DUAL",
                role_type="FARMER",
                constraints_json={
                    "prefer_organic": True,
                    "harvest_window_days": 9,
                    "banned_ingredients": ["百菌清", "代森锰锌"],
                },
                prefer_organic=True,
                harvest_window_days=12,
            )
        )
        session.add(
            FarmerProfileBannedIngredientORM(
                farmer_id="F-CJ-DUAL",
                ingredient_name="百菌清",
                seq=1,
            )
        )
        session.commit()

    first = constraints_backfill_script.backfill_constraints_json_to_normalized()
    second = constraints_backfill_script.backfill_constraints_json_to_normalized()

    assert first["harvest_window_backfilled"] == 0
    assert first["conflict_profiles"] == 1
    assert first["banned_ingredients_inserted"] == 1
    assert second["banned_ingredients_inserted"] == 0

    with session_scope() as session:
        profile = session.execute(
            select(FarmerProfileORM).where(FarmerProfileORM.farmer_id == "F-CJ-DUAL")
        ).scalar_one()
        ingredient_rows = session.execute(
            select(FarmerProfileBannedIngredientORM)
            .where(FarmerProfileBannedIngredientORM.farmer_id == "F-CJ-DUAL")
            .order_by(FarmerProfileBannedIngredientORM.seq.asc())
        ).scalars().all()

    assert profile.harvest_window_days == 12
    assert [row.ingredient_name for row in ingredient_rows] == ["百菌清", "代森锰锌"]


def test_constraints_backfill_main_prints_stats(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_tables(engine)

    monkeypatch.setattr(constraints_backfill_script, "engine", engine)
    monkeypatch.setattr(constraints_backfill_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F-CJ-MAIN",
                owner_user_id="F-CJ-MAIN",
                role_type="FARMER",
                constraints_json={"prefer_organic": True, "harvest_window_days": 7, "banned_ingredients": []},
                prefer_organic=False,
                harvest_window_days=None,
            )
        )
        session.commit()

    stdout = StringIO()
    with redirect_stdout(stdout):
        constraints_backfill_script.main()

    out = stdout.getvalue()
    assert "[constraints-backfill] migration completed" in out
    assert "[constraints-backfill] scanned_profiles=1" in out
    assert "[constraints-backfill] constraints_profiles=1" in out


def test_profile_repo_read_write_regression_after_constraints_backfill(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path, filename="constraints_backfill_repo.db")
    _create_tables(engine)

    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(constraints_backfill_script, "engine", engine)
    monkeypatch.setattr(constraints_backfill_script, "get_db_session", session_scope)
    monkeypatch.setenv("ENABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK", "true")

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F-CJ-REG",
                owner_user_id="F-CJ-REG",
                role_type="FARMER",
                name="回归测试",
                constraints_json={
                    "prefer_organic": True,
                    "harvest_window_days": 8,
                    "banned_ingredients": ["甲霜灵"],
                },
                prefer_organic=False,
                harvest_window_days=None,
            )
        )
        session.commit()

    constraints_backfill_script.backfill_constraints_json_to_normalized()

    loaded = profile_repo_mysql.get_profile("F-CJ-REG")
    assert loaded is not None
    assert loaded["constraints"] == {
        "prefer_organic": True,
        "harvest_window_days": 8,
        "banned_ingredients": ["甲霜灵"],
    }

    payload = {
        "farmer_id": "F-CJ-REG",
        "name": "回归测试",
        "owner_user_id": "F-CJ-REG",
        "display_name": "回归测试",
        "equipment": [],
        "constraints": {
            "prefer_organic": False,
            "harvest_window_days": 10,
            "banned_ingredients": ["甲霜灵", "乙膦铝"],
        },
        "bases": {},
    }
    saved = profile_repo_mysql.save_profile_payload(payload)
    assert saved["constraints"]["harvest_window_days"] == 10
    assert saved["constraints"]["banned_ingredients"] == ["甲霜灵", "乙膦铝"]
