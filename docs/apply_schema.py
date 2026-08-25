#!/usr/bin/env python3
"""docs/config.json の接続先 PostgreSQL に docs/schema.sql を適用する。

CI（.github/workflows/test.yml の e2e ジョブ）で、コンテナ起動直後の PostgreSQL に
対して使う。接続が確立するまで（コンテナの起動完了を待つため）リトライする。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "runner"))

from config_loader import load_config, get_postgres_config  # noqa: E402

DOCS = Path(__file__).resolve().parent


def main() -> int:
    config = get_postgres_config(load_config(str(DOCS / "config.json")))
    schema_sql = (DOCS / "schema.sql").read_text(encoding="utf-8")

    last_error: Exception | None = None
    for attempt in range(30):
        try:
            conn = psycopg2.connect(**config)
            break
        except psycopg2.OperationalError as e:
            last_error = e
            time.sleep(1)
    else:
        print(f"[apply_schema][FAIL] PostgreSQL に接続できませんでした: {last_error}", file=sys.stderr)
        return 1

    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        print("[apply_schema][OK] スキーマを適用しました")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
