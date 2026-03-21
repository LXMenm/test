# MySQL 迁移后的短期回滚指南

> 本文档继续保留，供已有引用路径使用；当前推荐阅读与维护的主文档为：`docs/mysql_migration_rollback.md`。

## 当前说明

如果你需要：
- 判断何时触发回滚；
- 区分 `dual` 与 `file` 回滚方式；
- 查看回滚后的验证清单；
- 了解当前仍保留的旧 JSON / JSONL 与迁移脚本；

请直接参考：

- `docs/mysql_migration_rollback.md`

## 保留本文件的原因

1. 仓库历史中已经存在对 `docs/mysql_rollback_guide.md` 的引用；
2. 论文草稿、开发留档或外部说明中可能仍引用旧路径；
3. 本文件作为兼容入口继续保留，避免文档路径变化带来引用断裂。
