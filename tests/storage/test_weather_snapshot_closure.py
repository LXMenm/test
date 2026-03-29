from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
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
    WeatherSnapshotORM,
)
from personalization.profile_models import BaseProfile, FarmerProfile
from personalization import profile_store
from repositories import profile_repo_mysql
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
        return FarmerProfile.model_validate(profile.model_dump())

    def _fake_persist_profile(payload_profile: FarmerProfile) -> None:
        persisted["called"] = True
        profile.bases["B001"] = payload_profile.bases["B001"]

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
    # refresh 返回兼容双 key，避免前端不同版本字段名不一致导致显示失败
    assert body["temperature_2m"] == 24.3
    assert body["weather_temperature_2m"] == 24.3
    assert body["wind_speed_10m"] == 2.1
    assert body["weather_wind_speed_10m"] == 2.1
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


def test_profile_save_and_get_expose_risk_tags_via_profile_store(monkeypatch) -> None:
    profile_state = FarmerProfile(
        farmer_id="F0001",
        owner_user_id="F0001",
        bases={},
    )

    @contextmanager
    def _fake_session_scope():
        class _FakeSession:
            pass

        yield _FakeSession()

    def _fake_validate_account_exists(_session: Any, _user_id: str) -> object:
        return object()

    def _fake_persist_profile(profile: FarmerProfile) -> None:
        profile = profile_store._ensure_profile_compatibility(profile)  # type: ignore[attr-defined]
        profile_state.farmer_id = profile.farmer_id
        profile_state.owner_user_id = profile.owner_user_id
        profile_state.display_name = profile.display_name
        profile_state.name = profile.name
        profile_state.bases = profile.bases
        profile_state.active_base_id = profile.active_base_id
        profile_state.constraints = profile.constraints
        profile_state.updated_at = profile.updated_at

    def _fake_load_profile(_farmer_id: str) -> FarmerProfile:
        return FarmerProfile.model_validate(profile_state.model_dump())

    monkeypatch.setattr(app_module, "get_db_session", _fake_session_scope)
    monkeypatch.setattr(app_module, "_validate_account_exists", _fake_validate_account_exists)
    monkeypatch.setattr(app_module, "persist_profile", _fake_persist_profile)
    monkeypatch.setattr(app_module, "load_profile", _fake_load_profile)

    client = TestClient(app_module.app)
    save_resp = client.post(
        "/api/profiles/F0001",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
        json={
            "farmer_id": "F0001",
            "owner_user_id": "F0001",
            "name": "测试农户",
            "display_name": "测试农户",
            "active_base_id": "B001",
            "bases": {
                "B001": {
                    "base_id": "B001",
                    "facility": "温室",
                    "relative_humidity_2m": 88,
                    "precipitation": 3.2,
                    "rain_risk": 75,
                    "growth_stage": "FRUITING",
                }
            },
        },
    )
    assert save_resp.status_code == 200
    saved_profile = save_resp.json()["profile"]
    assert saved_profile["bases"]["B001"]["risk_tags"]

    get_resp = client.get(
        "/api/profiles/F0001",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert get_resp.status_code == 200
    base_payload = get_resp.json()["bases"]["B001"]
    assert base_payload["risk_tags"]
    assert base_payload["risk_items"]
    assert base_payload["risk_updated_at"]


def test_refresh_weather_then_get_profile_contains_risk_tags(monkeypatch) -> None:
    profile_state = FarmerProfile(
        farmer_id="F0001",
        owner_user_id="F0001",
        bases={
            "B001": BaseProfile(
                base_id="B001",
                latitude=36.1,
                longitude=118.2,
                facility="温室",
                growth_stage="FRUITING",
            )
        },
        active_base_id="B001",
    )

    def _fake_load_profile(_farmer_id: str) -> FarmerProfile:
        return FarmerProfile.model_validate(profile_state.model_dump())

    def _fake_persist_profile(profile: FarmerProfile) -> None:
        profile = profile_store._ensure_profile_compatibility(profile)  # type: ignore[attr-defined]
        profile_state.bases = profile.bases
        profile_state.updated_at = profile.updated_at

    monkeypatch.setattr(app_module, "load_profile", _fake_load_profile)
    monkeypatch.setattr(app_module, "persist_profile", _fake_persist_profile)
    monkeypatch.setattr(app_module, "PROFILE_STORE_MODE", "file")
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
    refresh_resp = client.post(
        "/api/profiles/F0001/bases/B001/weather/refresh",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert refresh_resp.status_code == 200

    detail_resp = client.get(
        "/api/profiles/F0001",
        headers={"X-User-Id": "F0001", "X-User-Role": "USER"},
    )
    assert detail_resp.status_code == 200
    base_payload = detail_resp.json()["bases"]["B001"]
    assert base_payload["risk_tags"]
    assert base_payload["risk_items"]
    assert base_payload["risk_updated_at"]


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


def test_profile_repo_reads_weather_fields_from_explicit_columns_first_with_extra_json_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine, session_scope = _make_session_scope(tmp_path)
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)
    monkeypatch.setenv("ENABLE_BASE_EXTRA_LEGACY_FALLBACK", "true")

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F0001",
                owner_user_id="F0001",
                name="农户1",
                role_type="FARMER",
            )
        )
        session.add(
            FarmBaseORM(
                farmer_id="F0001",
                base_id="B001",
                weather_snapshot="阴天",
                relative_humidity_2m=None,
                precipitation=0.3,
                rain_risk=None,
                extra_json={
                    "relative_humidity_2m": 54.0,
                    "rain_risk": 20.0,
                    "weather_temperature_2m": 29.0,
                    "wind_speed_10m": 9.3,
                    "last_weather_refresh_at": "2026-03-27T08:00:00Z",
                    "lat": 31.2,
                    "lon": 121.5,
                },
            )
        )
        session.commit()

    payload = profile_repo_mysql.get_profile("F0001")
    assert payload is not None
    base = payload["bases"]["B001"]
    assert base["weather_snapshot"] == "阴天"
    # 经纬度列为空时，回退 extra_json(lat/lon)；避免前端按钮误判“缺少经纬度”。
    assert base["latitude"] == 31.2
    assert base["longitude"] == 121.5
    # 明确列优先：precipitation 取列值，不被 extra_json 覆盖
    assert base["precipitation"] == 0.3
    # 列为空时，回退 extra_json，保证历史数据可读
    assert base["relative_humidity_2m"] == 54.0
    assert base["rain_risk"] == 20.0
    assert base["weather_temperature_2m"] == 29.0
    assert base["weather_wind_speed_10m"] == 9.3
    assert base["last_weather_refresh_at"].startswith("2026-03-27T08:00:00")
