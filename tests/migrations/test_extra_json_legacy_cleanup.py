from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import scripts.migrations.migrate_extra_json_legacy_keys as cleanup_script
from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
)
from repositories import profile_repo_mysql


def _make_session_scope(tmp_path: Path, filename: str = "extra_json_legacy_cleanup.db") -> tuple[Any, Callable[[], Any]]:
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
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)


def test_cleanup_backfills_legacy_latlon_and_weather_keys(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    _create_tables(engine)

    monkeypatch.setattr(cleanup_script, "engine", engine)
    monkeypatch.setattr(cleanup_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmBaseORM(
                farmer_id="F-EXTRA-1",
                base_id="B-EXTRA-1",
                latitude=None,
                longitude=None,
                extra_json={
                    "lat": "36.12",
                    "lon": "118.76",
                    "temperature_2m": 26.5,
                    "wind_speed_10m": 3.2,
                    "weather_refreshed_at": "2026-03-28T08:00:00Z",
                },
            )
        )
        session.commit()

    with session_scope() as session:
        before = cleanup_script.audit_extra_json_legacy_dependency(session)
    assert before["legacy_only"] == 1

    stats = cleanup_script.cleanup_extra_json_legacy_keys(remove_legacy_keys=True)

    assert stats["scanned_bases"] == 1
    assert stats["legacy_hit_bases"] == 1
    assert stats["latitude_backfilled"] == 1
    assert stats["longitude_backfilled"] == 1
    assert stats["weather_temperature_2m_backfilled"] == 1
    assert stats["weather_wind_speed_10m_backfilled"] == 1
    assert stats["last_weather_refresh_at_backfilled"] == 1
    assert stats["legacy_keys_removed"] == 5
    assert stats["coordinate_conflicts"] == 0
    assert stats["weather_conflicts"] == 0

    with session_scope() as session:
        row = session.execute(select(FarmBaseORM)).scalar_one()
        after = cleanup_script.audit_extra_json_legacy_dependency(session)

    assert row.latitude == 36.12
    assert row.longitude == 118.76
    assert row.extra_json.get("weather_temperature_2m") == 26.5
    assert row.extra_json.get("weather_wind_speed_10m") == 3.2
    assert row.extra_json.get("last_weather_refresh_at") == "2026-03-28T08:00:00Z"
    assert "lat" not in row.extra_json
    assert "lon" not in row.extra_json
    assert "temperature_2m" not in row.extra_json
    assert "wind_speed_10m" not in row.extra_json
    assert "weather_refreshed_at" not in row.extra_json
    assert after["legacy_only"] == 0


def test_cleanup_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path, filename="extra_json_idempotent.db")
    _create_tables(engine)

    monkeypatch.setattr(cleanup_script, "engine", engine)
    monkeypatch.setattr(cleanup_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmBaseORM(
                farmer_id="F-EXTRA-2",
                base_id="B-EXTRA-2",
                extra_json={
                    "lat": 35.0,
                    "lon": 117.1,
                    "temperature_2m": 24,
                    "wind_speed_10m": 2.8,
                    "weather_refreshed_at": "2026-03-28T09:00:00Z",
                },
            )
        )
        session.commit()

    first = cleanup_script.cleanup_extra_json_legacy_keys(remove_legacy_keys=True)
    second = cleanup_script.cleanup_extra_json_legacy_keys(remove_legacy_keys=True)

    assert first["latitude_backfilled"] == 1
    assert first["legacy_keys_removed"] == 5
    assert second["latitude_backfilled"] == 0
    assert second["longitude_backfilled"] == 0
    assert second["weather_temperature_2m_backfilled"] == 0
    assert second["weather_wind_speed_10m_backfilled"] == 0
    assert second["last_weather_refresh_at_backfilled"] == 0
    assert second["legacy_keys_removed"] == 0


def test_cleanup_conflict_policy_keeps_primary_path(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path, filename="extra_json_conflict.db")
    _create_tables(engine)

    monkeypatch.setattr(cleanup_script, "engine", engine)
    monkeypatch.setattr(cleanup_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmBaseORM(
                farmer_id="F-EXTRA-3",
                base_id="B-EXTRA-3",
                latitude=30.1,
                longitude=120.2,
                extra_json={
                    "lat": 31.1,
                    "lon": 121.2,
                    "weather_temperature_2m": 25,
                    "temperature_2m": 24,
                    "weather_wind_speed_10m": 2.1,
                    "wind_speed_10m": 3.1,
                    "last_weather_refresh_at": "2026-03-28T10:00:00Z",
                    "weather_refreshed_at": "2026-03-28T09:59:00Z",
                },
            )
        )
        session.commit()

    stats = cleanup_script.cleanup_extra_json_legacy_keys(remove_legacy_keys=True)

    assert stats["latitude_backfilled"] == 0
    assert stats["longitude_backfilled"] == 0
    assert stats["coordinate_conflicts"] == 2
    assert stats["weather_conflicts"] == 3
    assert stats["legacy_keys_removed"] == 5
    assert stats["conflict_base_pairs"] == ["(F-EXTRA-3,B-EXTRA-3)"]

    with session_scope() as session:
        row = session.execute(select(FarmBaseORM)).scalar_one()

    assert row.latitude == 30.1
    assert row.longitude == 120.2
    assert row.extra_json["weather_temperature_2m"] == 25
    assert row.extra_json["weather_wind_speed_10m"] == 2.1
    assert row.extra_json["last_weather_refresh_at"] == "2026-03-28T10:00:00Z"


def test_profile_repo_read_regression_after_cleanup(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path, filename="extra_json_repo_regression.db")
    _create_tables(engine)

    monkeypatch.setattr(cleanup_script, "engine", engine)
    monkeypatch.setattr(cleanup_script, "get_db_session", session_scope)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(FarmerProfileORM(farmer_id="F-EXTRA-4", owner_user_id="F-EXTRA-4", role_type="FARMER"))
        session.add(
            FarmBaseORM(
                farmer_id="F-EXTRA-4",
                base_id="B-EXTRA-4",
                name="清洗回归基地",
                extra_json={
                    "temperature_2m": 23,
                    "wind_speed_10m": 1.9,
                    "weather_refreshed_at": "2026-03-28T07:00:00Z",
                },
            )
        )
        session.commit()

    cleanup_script.cleanup_extra_json_legacy_keys(remove_legacy_keys=True)

    loaded = profile_repo_mysql.get_profile("F-EXTRA-4")
    assert loaded is not None
    base = loaded["bases"]["B-EXTRA-4"]
    assert base["weather_temperature_2m"] == 23
    assert base["weather_wind_speed_10m"] == 1.9
    assert base["last_weather_refresh_at"] == "2026-03-28T07:00:00Z"


def test_cleanup_main_prints_stats_and_audit(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path, filename="extra_json_main.db")
    _create_tables(engine)

    monkeypatch.setattr(cleanup_script, "engine", engine)
    monkeypatch.setattr(cleanup_script, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmBaseORM(
                farmer_id="F-EXTRA-5",
                base_id="B-EXTRA-5",
                extra_json={"lat": 30.0, "temperature_2m": 20},
            )
        )
        session.commit()

    stdout = StringIO()
    with redirect_stdout(stdout):
        cleanup_script.main()

    output = stdout.getvalue()
    assert "[extra-json-legacy-cleanup] migration completed" in output
    assert "[extra-json-legacy-cleanup] scanned_bases=1" in output
    assert "[extra-json-legacy-cleanup] audit_before=" in output
    assert "[extra-json-legacy-cleanup] audit_after=" in output
