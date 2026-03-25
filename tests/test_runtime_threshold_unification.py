from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
import diagnosis_model as dm
import runtime_settings as rs


def _with_temp_runtime_path(tmp_path: Path, monkeypatch) -> Path:
    target = tmp_path / "admin_runtime_config.json"
    monkeypatch.setattr(rs, "RUNTIME_CONFIG_PATH", target)
    return target


def test_runtime_settings_default_and_migration(tmp_path, monkeypatch):
    path = _with_temp_runtime_path(tmp_path, monkeypatch)

    cfg = rs.load_admin_runtime_config()
    assert cfg["model_fusion"]["image_top1_threshold"] == 0.65
    assert cfg["model_fusion"]["low_margin_threshold"] == 0.03

    legacy = {
        "model_fusion": {
            "enable_image_model": True,
            "enable_text_model": True,
            "text_backend": "auto",
            "image_reliable_threshold": 0.81,
            "text_reliable_threshold": 0.52,
            "conflict_margin": 0.22,
            "need_confirm_threshold": 0.9,
        }
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    migrated = rs.load_admin_runtime_config()

    assert migrated["model_fusion"]["image_top1_threshold"] == 0.81
    assert migrated["model_fusion"]["text_top1_threshold"] == 0.52
    assert migrated["model_fusion"]["weak_conflict_min_text_top1"] == 0.22
    # need_confirm_threshold 已弃用，统一由 diagnosis_conf_threshold 驱动。
    assert migrated["model_fusion"]["diagnosis_conf_threshold"] == 0.5

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "image_reliable_threshold" not in saved["model_fusion"]
    assert "need_confirm_threshold" not in saved["model_fusion"]


def test_system_config_api_uses_new_fields(tmp_path, monkeypatch):
    _with_temp_runtime_path(tmp_path, monkeypatch)
    monkeypatch.setattr(app_module, "_get_request_actor", lambda request: {"role": "admin"})
    monkeypatch.setattr(app_module, "_require_admin", lambda actor: None)

    client = TestClient(app_module.app)

    got = client.get("/api/admin/system-config")
    assert got.status_code == 200
    payload = got.json()["config"]
    assert "image_top1_threshold" in payload["model_fusion"]

    payload["model_fusion"]["text_margin_threshold"] = 0.18
    payload["model_fusion"]["weak_conflict_min_image_top1"] = 0.66
    put = client.put("/api/admin/system-config", json=payload)
    assert put.status_code == 200

    got2 = client.get("/api/admin/system-config")
    cfg2 = got2.json()["config"]
    assert cfg2["model_fusion"]["text_margin_threshold"] == 0.18
    assert cfg2["model_fusion"]["weak_conflict_min_image_top1"] == 0.66


def test_fuse_multimodal_thresholds_use_runtime_new_keys(monkeypatch):
    engine = dm.DiseaseDiagnosisEngine.__new__(dm.DiseaseDiagnosisEngine)

    high_thresholds = {
        "image_top1_threshold": 0.95,
        "image_margin_threshold": 0.30,
        "text_top1_threshold": 0.95,
        "text_margin_threshold": 0.30,
        "weak_conflict_min_image_top1": 0.95,
        "weak_conflict_min_text_top1": 0.95,
        "diagnosis_conf_threshold": 0.50,
        "low_margin_threshold": 0.03,
    }
    monkeypatch.setattr(dm, "get_runtime_thresholds", lambda config=None: high_thresholds)
    _, meta_high = dm.DiseaseDiagnosisEngine.fuse_multimodal_probs(
        engine,
        image_probs={"A": 0.8, "B": 0.2},
        text_probs={"B": 0.8, "A": 0.2},
        prior_probs={},
    )
    assert meta_high["image_reliable"] is False
    assert meta_high["text_reliable"] is False

    low_thresholds = {
        **high_thresholds,
        "image_top1_threshold": 0.60,
        "image_margin_threshold": 0.10,
        "text_top1_threshold": 0.60,
        "text_margin_threshold": 0.10,
        "weak_conflict_min_image_top1": 0.50,
        "weak_conflict_min_text_top1": 0.50,
    }
    monkeypatch.setattr(dm, "get_runtime_thresholds", lambda config=None: low_thresholds)
    _, meta_low = dm.DiseaseDiagnosisEngine.fuse_multimodal_probs(
        engine,
        image_probs={"A": 0.8, "B": 0.2},
        text_probs={"B": 0.8, "A": 0.2},
        prior_probs={},
    )
    assert meta_low["image_reliable"] is True
    assert meta_low["text_reliable"] is True
    assert meta_low["weak_conflict_candidate"] is True


def test_new_fields_override_legacy_fields(tmp_path, monkeypatch):
    path = _with_temp_runtime_path(tmp_path, monkeypatch)
    payload = rs.DEFAULT_ADMIN_CONFIG
    payload = json.loads(json.dumps(payload))
    payload["model_fusion"]["image_top1_threshold"] = 0.9
    payload["model_fusion"]["image_reliable_threshold"] = 0.1
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    loaded = rs.load_admin_runtime_config()
    assert loaded["model_fusion"]["image_top1_threshold"] == 0.9

    thresholds = rs.get_runtime_thresholds(loaded)
    assert thresholds["image_top1_threshold"] == 0.9
