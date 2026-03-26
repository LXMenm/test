from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app as app_module
from db import Base
from fastapi import HTTPException
from mysql_models import UserAccountORM


def _build_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine, tables=[UserAccountORM.__table__])
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_sync_profile_sets_role_and_default_profile():
    session = _build_session()
    session.add(UserAccountORM(user_id="E0001", username="e0001", display_name="E0001", role="EXPERT", password="", status="ACTIVE"))
    session.commit()

    app_module._sync_user_account_from_profile(
        session=session,
        farmer_id="F0100",
        owner_user_id="E0001",
        role_type="ADMIN",
        display_name="管理员档案",
        set_as_default_profile=True,
    )
    session.commit()

    row = session.query(UserAccountORM).filter(UserAccountORM.user_id == "E0001").one()
    assert row.role == "ADMIN"
    assert row.linked_farmer_id == "F0100"


def test_sync_profile_does_not_clear_default_profile_when_not_set_default():
    session = _build_session()
    session.add(UserAccountORM(user_id="X0001", username="x0001", display_name="X0001", role="USER", password="", status="ACTIVE", linked_farmer_id="F0009"))
    session.commit()

    app_module._sync_user_account_from_profile(
        session=session,
        farmer_id="F0099",
        owner_user_id="X0001",
        role_type="EXPERT",
        display_name="专家档案",
        set_as_default_profile=False,
    )
    session.commit()

    row = session.query(UserAccountORM).filter(UserAccountORM.user_id == "X0001").one()
    assert row.role == "EXPERT"
    assert row.linked_farmer_id == "F0009"


def test_sync_profile_rejects_missing_or_inactive_account():
    session = _build_session()
    session.add(UserAccountORM(user_id="D0001", username="d0001", display_name="D0001", role="USER", password="", status="DISABLED"))
    session.commit()

    try:
        app_module._sync_user_account_from_profile(
            session=session,
            farmer_id="F0200",
            owner_user_id="MISSING",
            role_type="FARMER",
            display_name="",
            set_as_default_profile=True,
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "绑定账号不存在" in str(exc.detail)

    try:
        app_module._sync_user_account_from_profile(
            session=session,
            farmer_id="F0200",
            owner_user_id="D0001",
            role_type="FARMER",
            display_name="",
            set_as_default_profile=True,
        )
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "绑定账号不是激活状态" in str(exc.detail)

