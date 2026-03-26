from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import inspect, select, text

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db import engine, get_db_session  # noqa: E402
from mysql_models import (  # noqa: E402
    FarmBaseORM,
    FarmBaseRiskItemORM,
    FarmBaseRiskTagORM,
    FarmerProfileBannedIngredientORM,
    FarmerProfileEquipmentORM,
    FarmerProfileORM,
    UserAccountORM,
)


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _merge_profile_fields(source: FarmerProfileORM, target: FarmerProfileORM) -> list[str]:
    merged: list[str] = []
    for field in [
        "name",
        "display_name",
        "active_base_id",
        "farm_scale",
        "pesticide_access_level",
        "cultivation_mode",
        "experience_level",
        "risk_preference",
    ]:
        source_v = getattr(source, field, None)
        target_v = getattr(target, field, None)
        if (target_v is None or str(target_v).strip() == "") and source_v not in (None, ""):
            setattr(target, field, source_v)
            merged.append(field)
    return merged


def _rewrite_child_farmer_id(session: Any, src_farmer_id: str, dst_farmer_id: str) -> None:
    for model in [
        FarmBaseORM,
        FarmBaseRiskTagORM,
        FarmBaseRiskItemORM,
        FarmerProfileEquipmentORM,
        FarmerProfileBannedIngredientORM,
    ]:
        rows = session.execute(select(model).where(model.farmer_id == src_farmer_id)).scalars().all()
        for row in rows:
            row.farmer_id = dst_farmer_id


def _ensure_unique_owner_constraint(clean: bool, apply_changes: bool) -> tuple[bool, str]:
    inspector = inspect(engine)
    unique_constraints = inspector.get_unique_constraints("farmer_profiles")
    has_unique_owner = any(
        uc.get("name") == "uq_farmer_profiles_owner_user_id"
        or uc.get("column_names") == ["owner_user_id"]
        for uc in unique_constraints
    )
    if has_unique_owner:
        return True, "unique(owner_user_id) 已存在"
    if not (clean and apply_changes):
        return False, "未创建 unique(owner_user_id)：存在待人工处理数据或当前为 dry-run"
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE farmer_profiles ADD CONSTRAINT uq_farmer_profiles_owner_user_id UNIQUE (owner_user_id)"))
    return True, "已创建 unique(owner_user_id)"


def _ensure_owner_not_null(clean: bool, apply_changes: bool) -> tuple[bool, str]:
    inspector = inspect(engine)
    columns = inspector.get_columns("farmer_profiles")
    owner_col = next((item for item in columns if item.get("name") == "owner_user_id"), None)
    if owner_col and owner_col.get("nullable") is False:
        return True, "owner_user_id 已是 NOT NULL"
    if not (clean and apply_changes):
        return False, "未设置 NOT NULL：存在待人工处理数据或当前为 dry-run"
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE farmer_profiles MODIFY owner_user_id VARCHAR(64) NOT NULL"))
    return True, "已设置 owner_user_id 为 NOT NULL"


def main() -> None:
    parser = argparse.ArgumentParser(description="清洗并收口 farmer_profiles 的一账号一档案约束")
    parser.add_argument("--apply", action="store_true", help="实际写入数据库（默认仅 dry-run）")
    parser.add_argument("--report", default="data/migration_reports/one_account_one_profile_report.json", help="迁移报告输出路径")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "dry_run": not args.apply,
        "fixed_owner_from_farmer_id": [],
        "renamed_farmer_id_to_owner": [],
        "merged_duplicate_profile_fields": [],
        "manual_review_required": [],
    }

    FarmerProfileORM.__table__.create(bind=engine, checkfirst=True)
    UserAccountORM.__table__.create(bind=engine, checkfirst=True)

    with get_db_session() as session:
        account_ids = {
            _norm(row[0])
            for row in session.execute(select(UserAccountORM.user_id)).all()
            if _norm(row[0])
        }
        profiles = session.execute(select(FarmerProfileORM).order_by(FarmerProfileORM.id.asc())).scalars().all()

        profile_by_farmer: dict[str, FarmerProfileORM] = {
            _norm(item.farmer_id): item for item in profiles if _norm(item.farmer_id)
        }

        for profile in profiles:
            farmer_id = _norm(profile.farmer_id)
            owner = _norm(profile.owner_user_id)
            if owner:
                continue
            if farmer_id and farmer_id in account_ids:
                report["fixed_owner_from_farmer_id"].append({"profile_id": profile.id, "farmer_id": farmer_id, "owner_user_id": farmer_id})
                if args.apply:
                    profile.owner_user_id = farmer_id
            else:
                report["manual_review_required"].append(
                    {
                        "type": "missing_owner_no_account",
                        "profile_id": profile.id,
                        "farmer_id": farmer_id,
                        "message": "owner_user_id 为空且 farmer_id 找不到同名账号",
                    }
                )

        if args.apply:
            session.flush()

        profiles = session.execute(select(FarmerProfileORM).order_by(FarmerProfileORM.id.asc())).scalars().all()
        owner_groups: dict[str, list[FarmerProfileORM]] = defaultdict(list)
        for profile in profiles:
            owner = _norm(profile.owner_user_id)
            if owner:
                owner_groups[owner].append(profile)

        for owner, rows in owner_groups.items():
            canonical = next((item for item in rows if _norm(item.farmer_id) == owner), rows[0])

            if _norm(canonical.farmer_id) != owner:
                existing_target = profile_by_farmer.get(owner)
                if existing_target is None:
                    report["renamed_farmer_id_to_owner"].append(
                        {
                            "profile_id": canonical.id,
                            "from_farmer_id": _norm(canonical.farmer_id),
                            "to_farmer_id": owner,
                        }
                    )
                    if args.apply:
                        old_farmer = _norm(canonical.farmer_id)
                        canonical.farmer_id = owner
                        _rewrite_child_farmer_id(session, old_farmer, owner)
                        profile_by_farmer.pop(old_farmer, None)
                        profile_by_farmer[owner] = canonical
                elif existing_target.id != canonical.id:
                    merged = _merge_profile_fields(canonical, existing_target)
                    report["manual_review_required"].append(
                        {
                            "type": "farmer_id_owner_conflict",
                            "owner_user_id": owner,
                            "source_profile_id": canonical.id,
                            "target_profile_id": existing_target.id,
                            "message": "存在 farmer_id != owner_user_id 的冲突档案，已保留目标档案并记录人工核查",
                            "merged_fields": merged,
                        }
                    )
                    if args.apply:
                        canonical.owner_user_id = f"__DUPLICATE__{canonical.id}"
                        canonical.role_type = "FARMER"

            for duplicate in rows:
                if duplicate.id == canonical.id:
                    continue
                merged = _merge_profile_fields(duplicate, canonical)
                report["merged_duplicate_profile_fields"].append(
                    {
                        "owner_user_id": owner,
                        "duplicate_profile_id": duplicate.id,
                        "canonical_profile_id": canonical.id,
                        "merged_fields": merged,
                    }
                )
                report["manual_review_required"].append(
                    {
                        "type": "duplicate_owner_profiles",
                        "owner_user_id": owner,
                        "duplicate_profile_id": duplicate.id,
                        "canonical_profile_id": canonical.id,
                        "message": "同 owner 多档案：保留 canonical，重复档案已标记待人工处理",
                    }
                )
                if args.apply:
                    duplicate.owner_user_id = f"__DUPLICATE__{duplicate.id}"
                    duplicate.role_type = "FARMER"

        if args.apply:
            session.commit()

    has_manual = len(report["manual_review_required"]) > 0
    unique_ok, unique_msg = _ensure_unique_owner_constraint(clean=not has_manual, apply_changes=args.apply)
    not_null_ok, not_null_msg = _ensure_owner_not_null(clean=not has_manual, apply_changes=args.apply)
    report["constraints"] = {
        "unique_owner_user_id": {"ok": unique_ok, "message": unique_msg},
        "owner_user_id_not_null": {"ok": not_null_ok, "message": not_null_msg},
    }

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[one-account-one-profile] migration completed")
    print(f"[one-account-one-profile] dry_run={report['dry_run']}")
    print(f"[one-account-one-profile] report={report_path}")
    print(f"[one-account-one-profile] fixed_owner_from_farmer_id={len(report['fixed_owner_from_farmer_id'])}")
    print(f"[one-account-one-profile] renamed_farmer_id_to_owner={len(report['renamed_farmer_id_to_owner'])}")
    print(f"[one-account-one-profile] duplicate_merged={len(report['merged_duplicate_profile_fields'])}")
    print(f"[one-account-one-profile] manual_review_required={len(report['manual_review_required'])}")
    print(f"[one-account-one-profile] unique_owner_user_id={report['constraints']['unique_owner_user_id']['message']}")
    print(f"[one-account-one-profile] owner_user_id_not_null={report['constraints']['owner_user_id_not_null']['message']}")


if __name__ == "__main__":
    main()
