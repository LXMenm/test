from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app as app_module
from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
    UserAccountORM,
)
from repositories import profile_repo_mysql
from runtime_fallback_stats import get_fallback_stats, reset_fallback_stats


def _make_session_scope(tmp_path: Path, name: str) -> tuple[Any, Callable[[], Any]]:
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope


def test_profile_repo_fallback_stats_hits_are_recorded(monkeypatch, tmp_path: Path) -> None:
    reset_fallback_stats()
    monkeypatch.setenv("ENABLE_PROFILE_CONSTRAINTS_JSON_FALLBACK", "true")
    monkeypatch.setenv("ENABLE_BASE_EXTRA_LEGACY_FALLBACK", "true")
    engine, session_scope = _make_session_scope(tmp_path, "profile_fallback_stats.db")
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id="F0001",
                owner_user_id="",
                role_type="",
                name="农户1",
                constraints_json={
                    "prefer_organic": True,
                    "harvest_window_days": 9,
                    "banned_ingredients": ["LEGACY_BANNED"],
                },
                meta_json={"owner_user_id": "F_META", "role_type": "ADMIN", "display_name": "测试档案"},
            )
        )
        session.add(
            FarmBaseORM(
                farmer_id="F0001",
                base_id="B001",
                extra_json={
                    "lat": 31.2,
                    "lon": 121.5,
                    "temperature_2m": 28.5,
                    "wind_speed_10m": 9.1,
                    "weather_refreshed_at": "2026-03-20T08:00:00Z",
                },
            )
        )
        session.add(
            FarmBaseORM(
                farmer_id="F0001",
                base_id="B002",
            )
        )
        session.add(
            FarmBaseRiskItemORM(
                farmer_id="F0001",
                base_id="B002",
                payload_json={"code": "RAIN_RISK", "label": "降雨风险", "level": "high", "reason": "依赖 payload_json"},
            )
        )
        session.commit()

    payload = profile_repo_mysql.get_profile("F0001")
    assert payload is not None
    stats = get_fallback_stats()

    assert stats["profile.constraints_json_fallback"] >= 1
    assert stats["profile.meta.owner_user_id_fallback"] >= 1
    assert stats["profile.meta.role_type_fallback"] >= 1
    assert stats["base.extra.latlon_fallback"] >= 1
    assert stats["base.extra.weather_legacy_key_fallback"] >= 1


def test_admin_debug_fallback_stats_endpoint_and_auth_counter(monkeypatch, tmp_path: Path) -> None:
    reset_fallback_stats()
    engine, session_scope = _make_session_scope(tmp_path, "fallback_stats_api.db")
    UserAccountORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(app_module, "get_db_session", session_scope)

    with session_scope() as session:
        session.add(
            UserAccountORM(
                user_id="A0001",
                username="a0001",
                display_name="管理员",
                role="ADMIN",
                password="123456",
                status="ACTIVE",
                linked_farmer_id="A0001",
            )
        )
        session.add(
            UserAccountORM(
                user_id="F0001",
                username="f0001",
                display_name="农户",
                role="USER",
                password="123456",
                status="ACTIVE",
                linked_farmer_id="F0001",
            )
        )
        session.commit()

    client = TestClient(app_module.app)
    login_resp = client.post("/api/auth/login", json={"user_id": "F0001", "password": "123456"})
    assert login_resp.status_code == 200

    forbidden = client.get(
        "/api/admin/debug/fallback-stats",
        headers={"X-User-Role": "USER", "X-User-Id": "F0001"},
    )
    assert forbidden.status_code == 403

    admin_resp = client.get(
        "/api/admin/debug/fallback-stats",
        headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
    )
    assert admin_resp.status_code == 200
    stats = admin_resp.json()["stats"]
    assert stats["auth.linked_farmer_id_returned"] >= 1

    readiness_resp = client.get(
        "/api/admin/debug/fallback-readiness",
        headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
    )
    assert readiness_resp.status_code == 200
    readiness_items = readiness_resp.json()["items"]
    assert any(item["name"] == "auth.linked_farmer_id_returned" for item in readiness_items)
    assert all(item["name"] != "profile.equipment_json_fallback" for item in readiness_items)
    assert all(item["name"] != "base.risk_tags_json_fallback" for item in readiness_items)
    assert all(item["name"] != "base.risk_items_json_fallback" for item in readiness_items)
    assert all(item["name"] != "base.risk_item_structured_fallback" for item in readiness_items)

    readiness_forbidden = client.get(
        "/api/admin/debug/fallback-readiness",
        headers={"X-User-Role": "USER", "X-User-Id": "F0001"},
    )
    assert readiness_forbidden.status_code == 403


def test_save_profile_payload_stops_writing_redundant_compat_fields(monkeypatch, tmp_path: Path) -> None:
    reset_fallback_stats()
    engine, session_scope = _make_session_scope(tmp_path, "profile_stop_write.db")
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(profile_repo_mysql, "get_db_session", session_scope)

    payload = {
        "farmer_id": "F1001",
        "name": "停写测试",
        "owner_user_id": "F1001",
        "display_name": "停写测试显示名",
        "equipment": ["DRONE"],
        "constraints": {
            "prefer_organic": True,
            "harvest_window_days": 6,
            "banned_ingredients": ["LEGACY_ING"],
        },
        "bases": {
            "B1001": {
                "base_id": "B1001",
                "risk_tags": ["HIGH_HUMIDITY"],
                "risk_reasons": ["湿度高"],
                "risk_items": [
                    {"code": "HIGH_HUMIDITY", "label": "高湿", "level": "medium", "reason": "湿度高"}
                ],
                "extra_json": {
                    "lat": 31.2,
                    "lon": 121.5,
                    "temperature_2m": 27.8,
                    "wind_speed_10m": 8.6,
                    "weather_refreshed_at": "2026-03-20T00:00:00Z",
                },
                "weather_temperature_2m": 27.8,
                "weather_wind_speed_10m": 8.6,
                "last_weather_refresh_at": "2026-03-20T00:00:00Z",
            }
        },
    }
    profile_repo_mysql.save_profile_payload(payload)

    with session_scope() as session:
        profile_row = session.query(FarmerProfileORM).filter(FarmerProfileORM.farmer_id == "F1001").one()
        base_row = session.query(FarmBaseORM).filter(FarmBaseORM.base_id == "B1001").one()
        risk_item_rows = session.query(FarmBaseRiskItemORM).filter(FarmBaseRiskItemORM.base_id == "B1001").all()

    assert profile_row.constraints_json in (None, {})
    assert not (profile_row.meta_json or {}).get("owner_user_id")
    assert not (profile_row.meta_json or {}).get("role_type")

    assert (base_row.extra_json or {}).get("lat") is None
    assert (base_row.extra_json or {}).get("lon") is None
    assert (base_row.extra_json or {}).get("temperature_2m") is None
    assert (base_row.extra_json or {}).get("wind_speed_10m") is None
    assert (base_row.extra_json or {}).get("weather_refreshed_at") is None

    assert risk_item_rows
    assert all(row.payload_json for row in risk_item_rows)
