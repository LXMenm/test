"""
数据库初始化脚本
用于创建 MySQL 表结构。
"""

from __future__ import annotations

import pymysql
from urllib.parse import urlparse

# 首先连接到 MySQL 服务器（不指定数据库）来创建数据库
from db import engine as db_engine, Base
import mysql_models  # noqa: F401  # 确保 ORM 模型注册到 Base.metadata
from config import DATABASE_URL


def main() -> None:
    # 1. 解析数据库连接信息
    url = urlparse(DATABASE_URL)
    userinfo, hostinfo = url.netloc.split('@')
    username, password = userinfo.split(':')
    if ':' in hostinfo:
        host, port = hostinfo.split(':')
        port = int(port)
    else:
        host = hostinfo
        port = 3306
    
    print(f"连接到 MySQL 服务器: {host}:{port}")
    
    # 2. 用 pymysql 直接连接到服务器并创建数据库
    conn = pymysql.connect(
        host=host,
        port=port,
        user=username,
        password=password,
        charset='utf8mb4'
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute("CREATE DATABASE IF NOT EXISTS tomato_diagnosis CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
        print("✅ 数据库 'tomato_diagnosis' 已创建或已存在")
    finally:
        conn.close()
    
    # 3. 创建所有表
    print("正在创建表结构...")
    Base.metadata.create_all(bind=db_engine)
    
    # 4. 验证表已创建
    from sqlalchemy import inspect
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    print(f"✅ 已创建的表: {sorted(tables)}")
    
    print("\n🎉 MySQL 数据库和表初始化成功！")


if __name__ == "__main__":
    main()
