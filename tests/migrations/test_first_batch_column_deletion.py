from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect

from mysql_models import FarmBaseORM, FarmBaseRiskItemORM, FarmerProfileORM
import scripts.migrations.migrate_drop_first_batch_redundant_columns as drop_columns_script


DELETED_COLUMNS = {
    "farmer_profiles": {"equipment_json"},
    "farm_bases": {"risk_tags_json", "risk_items_json"},
    "farm_base_risk_items": {"risk_code", "risk_level", "risk_message"},
}


def _table_columns(engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    return {column["name"] for column in inspector.get_columns(table_name)}


def test_new_schema_baseline_excludes_first_batch_deleted_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'schema_baseline.db'}")

    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseORM.__table__.create(bind=engine, checkfirst=True)
    FarmBaseRiskItemORM.__table__.create(bind=engine, checkfirst=True)

    for table_name, removed_columns in DELETED_COLUMNS.items():
        assert removed_columns.isdisjoint(_table_columns(engine, table_name))


def test_drop_first_batch_migration_script_removes_columns_from_existing_tables(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'drop_columns.db'}")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE farmer_profiles (
                id INTEGER PRIMARY KEY,
                farmer_id VARCHAR(64),
                equipment_json TEXT,
                constraints_json TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE farm_bases (
                id INTEGER PRIMARY KEY,
                farmer_id VARCHAR(64),
                base_id VARCHAR(64),
                risk_tags_json TEXT,
                risk_items_json TEXT,
                risk_reasons_json TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE farm_base_risk_items (
                id INTEGER PRIMARY KEY,
                farmer_id VARCHAR(64),
                base_id VARCHAR(64),
                risk_code VARCHAR(64),
                risk_level VARCHAR(32),
                risk_message TEXT,
                payload_json TEXT
            )
            """
        )

    monkeypatch.setattr(drop_columns_script, "engine", engine)
    monkeypatch.setattr(
        drop_columns_script,
        "_column_exists",
        lambda conn, table_name, column_name: column_name in _table_columns(engine, table_name),
    )

    drop_columns_script.main()

    for table_name, removed_columns in DELETED_COLUMNS.items():
        assert removed_columns.isdisjoint(_table_columns(engine, table_name))
