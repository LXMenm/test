from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
from db import Base
from mysql_models import FarmerProfileORM, UserAccountORM


def _build_session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[UserAccountORM.__table__, FarmerProfileORM.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _seed_admin(SessionLocal):
    with SessionLocal() as session:
        session.add(
            UserAccountORM(
                user_id="A0001",
                username="admin",
                display_name="管理员",
                role="ADMIN",
                password="123456",
                linked_farmer_id="A0001",
                status="ACTIVE",
            )
        )
        session.commit()


def test_create_account_with_profile_defaults():
    SessionLocal = _build_session_factory()
    _seed_admin(SessionLocal)
    with SessionLocal() as session:
        account, profile = app_module._create_account_with_profile(
            session,
            username="zhangsan",
            display_name="张三",
            password="123456",
        )
        session.commit()

        assert account.user_id == "F0001"
        assert account.role == "USER"
        assert account.status == "ACTIVE"
        assert account.linked_farmer_id == "F0001"
        assert profile.farmer_id == "F0001"
        assert profile.owner_user_id == "F0001"


def test_admin_accounts_endpoints():
    SessionLocal = _build_session_factory()
    _seed_admin(SessionLocal)

    @contextmanager
    def _session_override():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    original_get_db_session = app_module.get_db_session
    original_seed = app_module.ensure_user_accounts_seeded
    app_module.get_db_session = _session_override
    app_module.ensure_user_accounts_seeded = lambda: None
    client = TestClient(app_module.app)

    try:
        forbidden = client.get("/api/admin/accounts", headers={"X-User-Role": "USER", "X-User-Id": "F0009"})
        assert forbidden.status_code == 403

        created = client.post(
            "/api/admin/accounts",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"username": "lisi", "display_name": "李四", "password": "123456"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["ok"] is True
        assert body["user_id"] == "F0001"
        assert body["farmer_id"] == "F0001"
        assert body["role"] == "USER"

        duplicate = client.post(
            "/api/admin/accounts",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"username": "lisi", "display_name": "李四2", "password": "123456", "role": "USER"},
        )
        assert duplicate.status_code == 400

        bad_role = client.post(
            "/api/admin/accounts",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"username": "wangwu", "display_name": "王五", "password": "123456", "role": "NOPE"},
        )
        assert bad_role.status_code == 400

        role_resp = client.post(
            "/api/admin/accounts/F0001/role",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"role": "EXPERT"},
        )
        assert role_resp.status_code == 200

        accounts = client.get("/api/admin/accounts", headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"})
        assert accounts.status_code == 200
        items = accounts.json()["items"]
        created_item = next(item for item in items if item["user_id"] == "F0001")
        assert created_item["username"] == "lisi"
        assert created_item["role"] == "EXPERT"
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed
