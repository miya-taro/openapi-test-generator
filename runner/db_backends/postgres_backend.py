"""DBシナリオの db_check（engine: postgres）を実行・検証する。"""
from __future__ import annotations
import re

import psycopg2
import psycopg2.extras

_IDENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def check(db_check, db_config: dict) -> tuple[bool, str]:
    """db_check を実行し (適合したか, 詳細メッセージ) を返す。"""
    conn = psycopg2.connect(**db_config)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if db_check.raw_sql:
                cur.execute(db_check.raw_sql)
            else:
                if not db_check.table:
                    return False, "db_check に table または raw_sql の指定がありません"
                sql, params = _build_select(db_check.table, db_check.where or {})
                cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    return _compare(rows, db_check.expect)


def _build_select(table: str, where: dict) -> tuple[str, list]:
    table_ident = _quote_ident(table)
    if not where:
        return f"SELECT * FROM {table_ident}", []
    conditions = " AND ".join(f"{_quote_ident(k)} = %s" for k in where)
    return f"SELECT * FROM {table_ident} WHERE {conditions}", list(where.values())


def _quote_ident(name: str) -> str:
    # table/column 名は YAML 作成者が指定する値だが、識別子として妥当な文字のみ許可する
    if not _IDENT_PATTERN.match(name):
        raise ValueError(f"不正な識別子です: {name!r}")
    return f'"{name}"'


def _compare(rows: list[dict], expect: dict) -> tuple[bool, str]:
    exists_expected = expect.get("exists", True)

    if not exists_expected:
        if rows:
            return False, f"存在しないはずの行が {len(rows)} 件見つかりました: {rows[0]}"
        return True, ""

    if not rows:
        return False, "該当する行が見つかりません"

    columns = expect.get("columns") or {}
    row = rows[0]
    mismatches = []
    for col, expected_val in columns.items():
        if col not in row:
            mismatches.append(f"{col}: カラムが存在しません")
            continue
        actual_val = row[col]
        if actual_val != expected_val:
            mismatches.append(f"{col}: 期待={expected_val!r} 実測={actual_val!r}")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""
