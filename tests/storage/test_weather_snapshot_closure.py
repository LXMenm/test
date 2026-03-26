from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app as app_module
from mysql_models import WeatherSnapshotORM
from personalization.profile_models import BaseProfile, FarmerProfile
from repositories import weather_repo_mysql


def _make_session_scope(tmp_path: Path) -> tuple[Any, Callable[[], Any]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'weather_snapshots.db'}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope


def test_weather_repo_upsert_and_query_with_filters(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    WeatherSnapshotORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(weather_repo_mysql, "get_db_session", session_scope)

    weather_repo_mysql.upsert_weather_snapshot_mysql(
        {
            "farmer_id": "F0001",
            "base_id": "B001",
            "lat": 36.1,
            "lon": 118.2,
            "temperature": 25.6,
            "humidity": 82.0,
            "precipitation": 1.1,
            "rain_probability": 70.0,
            "weather_code": "61",
            "weather_desc": "小雨",
            "source": "open-meteo",
            "snapshot_time": "2026-03-20T09:00:00Z",
            "raw_json": {"summary": "有降雨"},
        }
    )
    weather_repo_mysql.upsert_weather_snapshot_mysql(
        {
            "farmer_id": "F0001",
            "base_id": "B001",
            "lat": 36.2,
            "lon": 118.3,
            "temperature": 26.1,
            "humidity": 81.0,
            "precipitation": 0.4,
            "rain_probability": 30.0,
            "weather_code": "2",
            "weather_desc": "多云",
            "source": "open-meteo",
            "snapshot_time": "2026-03-21T09:00:00Z",
            "raw_json": {"summary": "转多云"},
        }
    )
    weather_repo_mysql.upsert_weather_snapshot_mysql(
        {
            "farmer_id": "F0002",
            "base_id": "B002",
            "lat": 37.1,
            "lon": 119.2,
            "temperature": 27.2,
            "humidity": 76.0,
            "precipitation": 0.0,
            "rain_probability": 10.0,
            "weather_code": "0",
            "weather_desc": "晴",
            "source": "open-meteo",
            "snapshot_time": "2026-03-22T09:00:00Z",
            "raw_json": {"summary": "晴天"},
        }
    )

    by_farmer = weather_repo_mysql.list_weather_snapshots_mysql(farmer_id="F0001")
    assert len(by_farmer) == 1
    assert by_farmer[0]["base_id"] == "B001"
    assert by_farmer[0]["weather_desc"] == "多云"
    assert by_farmer[0]["snapshot_time"].endswith("Z")

    by_time = weather_repo_mysql.list_weather_snapshots_mysql(
        farmer_id="F0002",
        start="2026-03-21",
        end="2026-03-23",
    )
    assert len(by_time) == 1
    assert by_time[0]["farmer_id"] == "F0002"
    assert isinstance(by_time[0]["raw_json"], dict)


def test_refresh_weather_writes_snapshot_and_keeps_profile_updates(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    WeatherSnapshotORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(weather_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(app_module, "upsert_weather_snapshot_mysql", weather_repo_mysql.upsert_weather_snapshot_mysql)
    monkeypatch.setattr(app_module, "list_weather_snapshots_mysql", weather_repo_mysql.list_weather_snapshots_mysql)
    monkeypatch.setattr(app_module, "PROFILE_STORE_MODE", "mysql")

    profile = FarmerProfile(
        farmer_id="F0001",
        owner_user_id="F0001",
        bases={
            "B001": BaseProfile(
                base_id="B001",
                latitude=36.1,
                longitude=118.2,
                name="测试基地",
            )
        },
        active_base_id="B001",
    )

    persisted: dict[str, Any] = {"called": False}

    def _fake_load_profile(_farmer_id: str) -> FarmerProfile:
        return profile

    def _fake_persist_profile(_profile: FarmerProfile) -> None:
        persisted["called"] = True

    monkeypatch.setattr(app_module, "load_profile", _fake_load_profile)
    monkeypatch.setattr(app_module, "persist_profile", _fake_persist_profile)
    monkeypatch.setattr(
        app_module,
        "weather_summary",
        lambda **kwargs: {
            "summary": "未来24小时降雨概率较高",
            "relative_humidity_2m": 85.0,
            "precipitation": 2.5,
            "rain_risk": 80.0,
            "temperature_2m": 24.3,
            "wind_speed_10m": 2.1,
            "weather_desc": "中雨",
        },
    )

    client = TestClient(app_module.app)
    resp = client.post(
        "/api/profiles/F0001/bases/B001/weather/refresh",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["weather_snapshot"] == "未来24小时降雨概率较高"
    assert persisted["called"] is True
    assert profile.bases["B001"].weather_snapshot == "未来24小时降雨概率较高"

    second = client.post(
        "/api/profiles/F0001/bases/B001/weather/refresh",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert second.status_code == 200

    with session_scope() as session:
        rows = session.execute(select(WeatherSnapshotORM)).scalars().all()
    assert len(rows) == 1
    assert rows[0].farmer_id == "F0001"
    assert rows[0].base_id == "B001"
    assert rows[0].weather_desc == "中雨"


def test_weather_snapshot_api_permission_and_admin_scope(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    WeatherSnapshotORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(weather_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setattr(app_module, "list_weather_snapshots_mysql", weather_repo_mysql.list_weather_snapshots_mysql)
    monkeypatch.setattr(app_module, "PROFILE_STORE_MODE", "mysql")

    weather_repo_mysql.upsert_weather_snapshot_mysql(
        {
            "farmer_id": "F0001",
            "base_id": "B001",
            "lat": 36.1,
            "lon": 118.2,
            "temperature": 25.6,
            "humidity": 82.0,
            "precipitation": 1.1,
            "rain_probability": 70.0,
            "weather_code": "61",
            "weather_desc": "小雨",
            "source": "open-meteo",
            "snapshot_time": "2026-03-20T09:00:00Z",
            "raw_json": {"summary": "有降雨"},
        }
    )
    weather_repo_mysql.upsert_weather_snapshot_mysql(
        {
            "farmer_id": "F0002",
            "base_id": "B002",
            "lat": 37.1,
            "lon": 119.2,
            "temperature": 27.2,
            "humidity": 76.0,
            "precipitation": 0.0,
            "rain_probability": 10.0,
            "weather_code": "0",
            "weather_desc": "晴",
            "source": "open-meteo",
            "snapshot_time": "2026-03-22T09:00:00Z",
            "raw_json": {"summary": "晴天"},
        }
    )

    client = TestClient(app_module.app)
    forbidden = client.get(
        "/api/weather/snapshots",
        params={"farmer_id": "F0002"},
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert forbidden.status_code == 403

    admin_resp = client.get(
        "/api/weather/snapshots",
        params={"farmer_id": "F0002", "start": "2026-03-21", "end": "2026-03-23"},
        headers={"X-User-Id": "A0001", "X-User-Role": "ADMIN"},
    )
    assert admin_resp.status_code == 200
    items = admin_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["farmer_id"] == "F0002"
    assert items[0]["snapshot_time"].endswith("Z")
