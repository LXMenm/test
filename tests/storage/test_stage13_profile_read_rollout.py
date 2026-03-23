from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app as app_module
import personalization.profile_store as profile_store


class _InMemoryProfileMysqlRepo:
    def __init__(self, initial_profiles: dict[str, dict[str, Any]] | None = None):
        self._profiles = {
            farmer_id: dict(payload)
            for farmer_id, payload in (initial_profiles or {}).items()
        }

    def get_profile_mysql(self, farmer_id: str) -> dict[str, Any] | None:
        payload = self._profiles.get(farmer_id)
        return dict(payload) if isinstance(payload, dict) else None

    def list_profile_ids_mysql(self) -> list[str]:
        return sorted(self._profiles.keys())

    def list_all_base_ids_mysql(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for farmer_id, payload in self._profiles.items():
            bases = payload.get("bases") if isinstance(payload.get("bases"), dict) else {}
            for base_id in bases.keys():
                mapping[str(base_id)] = farmer_id
        return dict(sorted(mapping.items()))

    def save_profile_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        farmer_id = str(payload.get("farmer_id") or "").strip()
        if not farmer_id:
            raise ValueError("payload.farmer_id is required")
        self._profiles[farmer_id] = dict(payload)
        return dict(payload)

    def delete_profile_mysql(self, farmer_id: str) -> None:
        self._profiles.pop(farmer_id, None)

    def export(self) -> dict[str, dict[str, Any]]:
        return {farmer_id: dict(payload) for farmer_id, payload in self._profiles.items()}


def _profile_payload(farmer_id: str, *, base_id: str = "B001", name: str = "测试农户") -> dict[str, Any]:
    return {
        "farmer_id": farmer_id,
        "name": name,
        "schema_version": "1.2",
        "updated_at": "2026-03-20T00:00:00Z",
        "active_base_id": base_id,
        "confirm_when_low_confidence": True,
        "farm_scale": "MEDIUM",
        "pesticide_access_level": "LIMITED",
        "equipment": ["BACKPACK_SPRAYER"],
        "cultivation_mode": "SOIL",
        "experience_level": "INTERMEDIATE",
        "risk_preference": "BALANCED",
        "constraints": {"prefer_organic": True, "banned_ingredients": ["百菌清"]},
        "bases": {
            base_id: {
                "base_id": base_id,
                "name": "一号棚",
                "location": "山东寿光",
                "province": "山东",
                "facility": "GREENHOUSE",
                "environment": "温室",
                "growth_stage": "FLOWERING",
                "sowing_date": "2026-03-01",
            }
        },
    }


def _install_profile_repo(monkeypatch, tmp_path: Path, *, mode: str, repo: _InMemoryProfileMysqlRepo) -> None:
    monkeypatch.setattr(profile_store, "PROFILE_DIR", tmp_path / "profiles")
    monkeypatch.setattr(profile_store, "PROFILE_STORE_MODE", mode)
    monkeypatch.setattr(
        profile_store,
        "_get_mysql_repo",
        lambda: {
            "get_profile_mysql": repo.get_profile_mysql,
            "list_profile_ids_mysql": repo.list_profile_ids_mysql,
            "list_all_base_ids_mysql": repo.list_all_base_ids_mysql,
            "save_profile_payload": repo.save_profile_payload,
            "delete_profile_mysql": repo.delete_profile_mysql,
        },
    )


def test_dual_profile_routes_create_read_delete_and_context(monkeypatch, tmp_path: Path) -> None:
    repo = _InMemoryProfileMysqlRepo()
    _install_profile_repo(monkeypatch, tmp_path, mode="dual", repo=repo)
    client = TestClient(app_module.app)

    create_resp = client.post("/api/profiles", json={"name": "Dual 用户"})
    assert create_resp.status_code == 200
    farmer_id = create_resp.json()["id"]

    save_resp = client.post(
        f"/api/profiles/{farmer_id}",
        json=_profile_payload(farmer_id, base_id="DBASE", name="Dual 用户"),
    )
    assert save_resp.status_code == 200
    assert save_resp.json() == {"ok": True}

    list_resp = client.get("/api/profiles")
    assert list_resp.status_code == 200
    assert any(item["id"] == farmer_id for item in list_resp.json()["profiles"])

    detail_resp = client.get(f"/api/profiles/{farmer_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["active_base_id"] == "DBASE"

    base_ids_resp = client.get("/api/profiles/base-ids")
    assert base_ids_resp.status_code == 200
    assert {"base_id": "DBASE", "farmer_id": farmer_id} in base_ids_resp.json()["items"]

    profile, base_profile, resolved_base_id = app_module._resolve_profile_and_base(farmer_id, "DBASE")
    assert profile is not None
    assert base_profile is not None
    assert resolved_base_id == "DBASE"

    assert farmer_id in repo.export()

    delete_resp = client.delete(f"/api/profiles/{farmer_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json() == {"ok": True}
    assert farmer_id not in repo.export()



def test_mysql_profile_routes_and_context_read_from_mysql_repo(monkeypatch, tmp_path: Path) -> None:
    initial_payload = _profile_payload("FMYSQL", base_id="MB001", name="MySQL 用户")
    repo = _InMemoryProfileMysqlRepo({"FMYSQL": initial_payload})
    _install_profile_repo(monkeypatch, tmp_path, mode="mysql", repo=repo)
    client = TestClient(app_module.app)

    list_resp = client.get("/api/profiles")
    assert list_resp.status_code == 200
    assert any(item["id"] == "FMYSQL" for item in list_resp.json()["profiles"])

    detail_resp = client.get("/api/profiles/FMYSQL")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["name"] == "MySQL 用户"
    assert detail_resp.json()["active_base_id"] == "MB001"

    base_ids_resp = client.get("/api/profiles/base-ids")
    assert base_ids_resp.status_code == 200
    assert base_ids_resp.json()["items"] == [{"base_id": "MB001", "farmer_id": "FMYSQL"}]

    profile, base_profile, resolved_base_id = app_module._resolve_profile_and_base("FMYSQL", "MB001")
    assert profile is not None
    assert base_profile is not None
    assert resolved_base_id == "MB001"

    create_resp = client.post("/api/profiles", json={"name": "新 MySQL 用户"})
    assert create_resp.status_code == 200
    created_farmer_id = create_resp.json()["id"]
    assert created_farmer_id in repo.export()

    delete_resp = client.delete("/api/profiles/FMYSQL")
    assert delete_resp.status_code == 200
    assert "FMYSQL" not in repo.export()
