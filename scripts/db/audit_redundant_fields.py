"""第一优先级冗余字段离线审计脚本（只读）。"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from sqlalchemy import create_engine, text

SQL_PATH = Path(__file__).with_name("audit_redundant_fields.sql")


def _load_queries() -> list[str]:
    raw = SQL_PATH.read_text(encoding="utf-8")
    blocks: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        striped = line.strip()
        if not striped or striped.startswith("--"):
            continue
        current.append(line)
        if striped.endswith(";"):
            blocks.append("\n".join(current).strip())
            current = []
    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _print_queries(queries: Iterable[str]) -> None:
    for idx, query in enumerate(queries, start=1):
        print(f"\n--- Query #{idx} ---")
        print(query)


def _execute_queries(database_url: str, queries: Iterable[str]) -> None:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        for idx, query in enumerate(queries, start=1):
            print(f"\n--- Result #{idx} ---")
            rows = conn.execute(text(query)).mappings().all()
            if not rows:
                print("(no rows)")
                continue
            for row in rows:
                print(dict(row))


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit redundant fields (read-only)")
    parser.add_argument(
        "--database-url",
        default="",
        help="SQLAlchemy DB URL. If omitted, script only prints audit SQL.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute read-only SQL queries. Default is print-only.",
    )
    args = parser.parse_args()

    queries = _load_queries()
    if not args.execute:
        print("[audit] print-only mode (no DB execution)")
        _print_queries(queries)
        return

    if not args.database_url.strip():
        raise SystemExit("--execute requires --database-url")

    print("[audit] execute mode (read-only SELECT)")
    _execute_queries(args.database_url.strip(), queries)


if __name__ == "__main__":
    main()
