from db import get_db_session
from sqlalchemy import text

# 只审计 constraints_json 相关的查询
queries = {
    "B1": """SELECT COUNT(*) AS profile_count_constraints_json_only FROM farmer_profiles fp WHERE JSON_VALID(fp.constraints_json) AND JSON_LENGTH(fp.constraints_json) > 0 AND fp.prefer_organic = 0 AND fp.harvest_window_days IS NULL AND NOT EXISTS (SELECT 1 FROM farmer_profile_banned_ingredients bi WHERE bi.farmer_id = fp.farmer_id);""",
    "B2": """SELECT COUNT(*) AS profile_count_constraints_dual_store FROM farmer_profiles fp WHERE JSON_VALID(fp.constraints_json) AND JSON_LENGTH(fp.constraints_json) > 0 AND (fp.prefer_organic = 1 OR fp.harvest_window_days IS NOT NULL OR EXISTS (SELECT 1 FROM farmer_profile_banned_ingredients bi WHERE bi.farmer_id = fp.farmer_id));"""
}

with get_db_session() as session:
    results = {}
    for key, query in queries.items():
        try:
            result = session.execute(text(query)).scalar()
            results[key] = result
        except Exception as e:
            results[key] = f"Error: {str(e)}"

print("=== constraints_json 审计结果 ===")
print(f"数据库: {session.bind.url}")
print()
print(f"只靠 constraints_json 表达约束的档案数: {results.get('B1', 'Error')}")
print(f"双存档案数: {results.get('B2', 'Error')}")
print()

# 判定
b1 = results.get('B1', 0)
if isinstance(b1, int) and b1 == 0:
    print("✅ 可以进入删列执行轮")
    print("建议：删除 farmer_profiles.constraints_json 字段")
else:
    print("❌ 还不能删，存在只依赖 constraints_json 的档案")
    print("建议：先补迁移剩余档案")
