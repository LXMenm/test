from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import sys
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from mysql_models import (
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
)
from repositories import profile_repo_mysql
import scripts.migrations.migrate_profile_normalized as migrate_profile_script


def _profile_payload() -> dict[str, Any]:
    return {
        'farmer_id': 'FMYSQL-NORMALIZED',
        'name': '标准化农户',
        'schema_version': '1.2',
        'updated_at': '2026-03-20T00:00:00Z',
        'active_base_id': 'B001',
        'confirm_when_low_confidence': True,
        'farm_scale': 'MEDIUM',
        'pesticide_access_level': 'LIMITED',
        'equipment': ['BACKPACK_SPRAYER', 'DRONE'],
        'cultivation_mode': 'SOIL',
        'experience_level': 'INTERMEDIATE',
        'risk_preference': 'BALANCED',
        'constraints': {
            'prefer_organic': True,
            'harvest_window_days': 9,
            'banned_ingredients': ['百菌清', '代森锰锌'],
        },
        'bases': {
            'B001': {
                'base_id': 'B001',
                'internal_base_uid': 'uid-b001',
                'name': '一号棚',
                'location': '山东寿光',
                'province': '山东',
                'facility': 'GREENHOUSE',
                'environment': '温室',
                'growth_stage': 'FLOWERING',
                'sowing_date': '2026-03-01',
            }
        },
    }


def _make_session_scope(tmp_path: Path) -> tuple[Any, Callable[[], Any], Any]:
    engine = create_engine(f"sqlite:///{tmp_path / 'profile_normalized.db'}")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    @contextmanager
    def _session_scope():
        session: Session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    return engine, _session_scope, SessionLocal


def _create_profile_tables(engine: Any) -> None:
    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileEquipmentORM.__table__.create(bind=engine, checkfirst=True)
    FarmerProfileBannedIngredientORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskTagORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)


def test_save_profile_payload_writes_main_and_normalized_child_tables(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope, _ = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, 'get_db_session', session_scope)

    saved = profile_repo_mysql.save_profile_payload(_profile_payload())

    assert saved['equipment'] == ['BACKPACK_SPRAYER', 'DRONE']
    assert saved['constraints']['banned_ingredients'] == ['百菌清', '代森锰锌']

    with session_scope() as session:
        profile_row = session.execute(select(FarmerProfileORM)).scalar_one()
        equipment_rows = session.execute(
            select(FarmerProfileEquipmentORM).order_by(FarmerProfileEquipmentORM.seq.asc())
        ).scalars().all()
        ingredient_rows = session.execute(
            select(FarmerProfileBannedIngredientORM).order_by(FarmerProfileBannedIngredientORM.seq.asc())
        ).scalars().all()
        base_rows = session.execute(select(FarmBaseORM)).scalars().all()

    assert profile_row.prefer_organic is True
    assert profile_row.harvest_window_days == 9
    # constraints_json 字段已删除，不再断言
    assert not (profile_row.meta_json or {}).get("owner_user_id")
    assert not (profile_row.meta_json or {}).get("role_type")
    assert [row.equipment_code for row in equipment_rows] == ['BACKPACK_SPRAYER', 'DRONE']
    assert [row.ingredient_name for row in ingredient_rows] == ['百菌清', '代森锰锌']
    assert len(base_rows) == 1


def test_load_profile_prefers_normalized_children_but_keeps_payload_shape(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope, _ = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, 'get_db_session', session_scope)

    profile_repo_mysql.save_profile_payload(_profile_payload())

    # constraints_json 字段已删除，此测试逻辑已不适用
    # 直接读取验证数据正确
    loaded = profile_repo_mysql.get_profile('FMYSQL-NORMALIZED')

    assert loaded is not None
    assert loaded['equipment'] == ['BACKPACK_SPRAYER', 'DRONE']
    assert loaded['constraints'] == {
        'prefer_organic': True,
        'harvest_window_days': 9,
        'banned_ingredients': ['百菌清', '代森锰锌'],
    }
    assert set(loaded.keys()) >= {'farmer_id', 'equipment', 'constraints', 'bases'}


# constraints_json 字段已删除，此测试已不适用，跳过
def test_load_profile_falls_back_to_legacy_constraints_json_when_children_are_empty(monkeypatch, tmp_path: Path) -> None:
    # constraints_json 字段已删除，此 fallback 测试不再适用
    pass


def test_migrate_profile_normalized_script_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    engine, session_scope, SessionLocal = _make_session_scope(tmp_path)
    _create_profile_tables(engine)
    monkeypatch.setattr(profile_repo_mysql, 'get_db_session', session_scope)
    monkeypatch.setattr(migrate_profile_script, 'engine', engine)

    payload = _profile_payload()
    with session_scope() as session:
        session.add(
            FarmerProfileORM(
                farmer_id=payload['farmer_id'],
                name=payload['name'],
                owner_user_id=payload['farmer_id'],
                schema_version='1.2',
                confirm_when_low_confidence=True,
                prefer_organic=True,
                harvest_window_days=9,
            )
        )
        # constraints_json 已删除，banned_ingredients 直接从子表读取
        session.add(
            FarmerProfileBannedIngredientORM(
                farmer_id=payload['farmer_id'],
                ingredient_name='百菌清',
                seq=1,
            )
        )
        session.add(
            FarmerProfileBannedIngredientORM(
                farmer_id=payload['farmer_id'],
                ingredient_name='代森锰锌',
                seq=2,
            )
        )
        session.add(
            FarmBaseORM(
                farmer_id=payload['farmer_id'],
                base_id='B001',
                internal_base_uid='uid-b001',
                name='一号棚',
            )
        )
        session.commit()

    monkeypatch.setattr(migrate_profile_script, 'list_profile_ids', profile_repo_mysql.list_profile_ids)
    monkeypatch.setattr(migrate_profile_script, 'get_profile', profile_repo_mysql.get_profile)
    monkeypatch.setattr(sys, 'argv', ['migrate_profile_normalized.py'])

    first_stdout = StringIO()
    with redirect_stdout(first_stdout):
        migrate_profile_script.main()

    with session_scope() as session:
        equipment_rows_first = session.execute(select(FarmerProfileEquipmentORM)).scalars().all()
        ingredient_rows_first = session.execute(select(FarmerProfileBannedIngredientORM)).scalars().all()

    second_stdout = StringIO()
    with redirect_stdout(second_stdout):
        migrate_profile_script.main()

    with session_scope() as session:
        equipment_rows_second = session.execute(select(FarmerProfileEquipmentORM)).scalars().all()
        ingredient_rows_second = session.execute(select(FarmerProfileBannedIngredientORM)).scalars().all()

    assert len(equipment_rows_first) == len(equipment_rows_second) == 0
    assert len(ingredient_rows_first) == len(ingredient_rows_second) == 2
    assert '[profile-normalize] profiles=1' in first_stdout.getvalue()
    assert '[profile-normalize] banned_ingredient_rows=2' in second_stdout.getvalue()
