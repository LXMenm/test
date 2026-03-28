from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import select
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
        assert account.password != "123456"
        assert app_module._verify_password("123456", account.password) is True
        assert profile.farmer_id == "F0001"
        assert profile.owner_user_id == "F0001"


def test_register_success():
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
        resp = client.post(
            "/api/auth/register",
            json={"username": "newuser01", "display_name": "新用户", "password": "123456"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "USER"
        assert body["user_id"]
        assert body["linked_farmer_id"] == body["user_id"]
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed


def test_registered_user_can_login_by_username():
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
        register_resp = client.post(
            "/api/auth/register",
            json={"username": "newuser02", "display_name": "新用户二", "password": "123456"},
        )
        assert register_resp.status_code == 200

        login_resp = client.post(
            "/api/auth/login",
            json={"username": "newuser02", "password": "123456"},
        )
        assert login_resp.status_code == 200
        body = login_resp.json()
        assert body["username"] == "newuser02"
        assert body["display_name"] == "新用户二"
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed


def test_plaintext_password_login_and_upgrade():
    SessionLocal = _build_session_factory()
    _seed_admin(SessionLocal)

    with SessionLocal() as session:
        session.add(
            UserAccountORM(
                user_id="F0100",
                username="legacy100",
                display_name="旧账号",
                role="USER",
                password="123456",
                linked_farmer_id="F0100",
                status="ACTIVE",
            )
        )
        session.add(
            FarmerProfileORM(
                farmer_id="F0100",
                owner_user_id="F0100",
                display_name="旧账号",
                name="旧账号",
                role_type="FARMER",
            )
        )
        session.commit()

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
        login_resp = client.post(
            "/api/auth/login",
            json={"user_id": "F0100", "password": "123456"},
        )
        assert login_resp.status_code == 200

        with SessionLocal() as session:
            upgraded = session.execute(
                select(UserAccountORM).where(UserAccountORM.user_id == "F0100")
            ).scalar_one_or_none()
            assert upgraded is not None
            assert upgraded.password != "123456"
            assert app_module._verify_password("123456", upgraded.password) is True
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed


def test_register_duplicate_username_failed():
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
        first = client.post(
            "/api/auth/register",
            json={"username": "dupuser", "display_name": "重复用户", "password": "123456"},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/auth/register",
            json={"username": "dupuser", "display_name": "重复用户2", "password": "123456"},
        )
        assert second.status_code == 400
        assert "用户名已存在" in str(second.json().get("detail", ""))
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed


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

        deprecated_create_profile = client.post(
            "/api/profiles",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"owner_user_id": "A0001", "display_name": "deprecated"},
        )
        assert deprecated_create_profile.status_code == 400

        deprecated_delete_profile = client.delete(
            "/api/profiles/F0001",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
        )
        assert deprecated_delete_profile.status_code == 400

        role_resp = client.post(
            "/api/admin/accounts/F0001/role",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
            json={"role": "EXPERT"},
        )
        assert role_resp.status_code == 200

        delete_resp = client.delete(
            "/api/admin/accounts/F0001",
            headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"},
        )
        assert delete_resp.status_code == 200

        accounts = client.get("/api/admin/accounts", headers={"X-User-Role": "ADMIN", "X-User-Id": "A0001"})
        assert accounts.status_code == 200
        items = accounts.json()["items"]
        assert all(item["user_id"] != "F0001" for item in items)
    finally:
        app_module.get_db_session = original_get_db_session
        app_module.ensure_user_accounts_seeded = original_seed
