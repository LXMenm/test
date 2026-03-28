# constraints_json 字段已从生产数据库删除
# 这些测试验证的是补迁移脚本逻辑，现已不再适用
# 保留文件作为历史记录，但所有测试已跳过

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="constraints_json 字段已删除，补迁移脚本已完成使命")
def test_constraints_backfill_fills_json_only_profile_and_reduces_json_only_count():
    pass


@pytest.mark.skip(reason="constraints_json 字段已删除，补迁移脚本已完成使命")
def test_constraints_backfill_is_idempotent_and_preserves_existing_normalized_data():
    pass


@pytest.mark.skip(reason="constraints_json 字段已删除，补迁移脚本已完成使命")
def test_constraints_backfill_main_prints_stats():
    pass


@pytest.mark.skip(reason="constraints_json 字段已删除，补迁移脚本已完成使命")
def test_profile_repo_read_write_regression_after_constraints_backfill():
    pass
