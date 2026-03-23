from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

import app as app_module


@pytest.fixture
def restore_app_module(monkeypatch):
    yield
    monkeypatch.delenv("IMAGE_UPLOAD_DIR", raising=False)
    monkeypatch.delenv("IMAGE_UPLOAD_TTL_HOURS", raising=False)
    importlib.reload(app_module)


def _reload_app(monkeypatch, *, upload_dir: Path | None = None, ttl_hours: int | None = None):
    if upload_dir is None:
        monkeypatch.delenv("IMAGE_UPLOAD_DIR", raising=False)
    else:
        monkeypatch.setenv("IMAGE_UPLOAD_DIR", str(upload_dir))

    if ttl_hours is None:
        monkeypatch.delenv("IMAGE_UPLOAD_TTL_HOURS", raising=False)
    else:
        monkeypatch.setenv("IMAGE_UPLOAD_TTL_HOURS", str(ttl_hours))

    return importlib.reload(app_module)


def test_upload_dir_defaults_to_persistent_directory(monkeypatch, restore_app_module):
    module = _reload_app(monkeypatch)

    assert module.IMAGE_UPLOAD_DIR == "data/uploads"
    assert module.UPLOAD_DIR == Path("data/uploads")
    assert module.UPLOAD_DIR.exists()
    assert module.IMAGE_UPLOAD_TTL_HOURS == 0


def test_cleanup_old_uploads_disabled_by_default(monkeypatch, tmp_path, restore_app_module):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    module = _reload_app(monkeypatch, upload_dir=upload_dir)

    old_image = module.UPLOAD_DIR / "old.jpg"
    old_image.write_bytes(b"old-image")
    stale_ts = old_image.stat().st_mtime - 48 * 3600
    os.utime(old_image, (stale_ts, stale_ts))

    module.cleanup_old_uploads()

    assert old_image.exists()


def test_cleanup_old_uploads_removes_expired_images_when_ttl_enabled(monkeypatch, tmp_path, restore_app_module):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    module = _reload_app(monkeypatch, upload_dir=upload_dir, ttl_hours=24)

    old_image = module.UPLOAD_DIR / "old.jpg"
    fresh_image = module.UPLOAD_DIR / "fresh.jpg"
    old_image.write_bytes(b"old-image")
    fresh_image.write_bytes(b"fresh-image")

    stale_ts = old_image.stat().st_mtime - 48 * 3600
    os.utime(old_image, (stale_ts, stale_ts))

    module.cleanup_old_uploads()

    assert not old_image.exists()
    assert fresh_image.exists()
