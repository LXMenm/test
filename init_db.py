"""
数据库初始化脚本
用于创建 MySQL 表结构。
"""

from __future__ import annotations

from db import Base, engine
import mysql_models  # noqa: F401  # 确保 ORM 模型注册到 Base.metadata


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("MySQL tables initialized successfully.")


if __name__ == "__main__":
    main()
