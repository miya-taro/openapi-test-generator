"""DBシナリオの db_check（engine: postgres）を実行・検証する。"""
from __future__ import annotations
import re
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras

from db_backends import invariant_eval

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

    return _compare(rows, db_check.expect, db_check.invariants)


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


def _values_equal(actual_val: object, expected_val: object) -> bool:
    """DB実測値とYAMLの期待値を比較する。

    psycopg2はPostgreSQLの NUMERIC/DECIMAL 列を Decimal で返すが、YAMLシナリオ側の
    期待値（例: price: 19.99）はPythonの float としてパースされる。Decimal と float を
    直接 == で比較すると、float の「見た目通り」の値ではなく二進浮動小数点としての
    厳密値で比較されるため（例: Decimal("19.99") == 19.99 は False。19.99 は二進数で
    正確に表現できないため）、値としては等しいのに誤ってNG判定してしまう。
    どちらかが Decimal の場合は、両者を文字列経由でDecimal化してから比較することで、
    人間が書いた10進数リテラルの見た目通りに比較する。
    """
    if isinstance(actual_val, Decimal) or isinstance(expected_val, Decimal):
        try:
            return Decimal(str(actual_val)) == Decimal(str(expected_val))
        except (InvalidOperation, ValueError, TypeError):
            return actual_val == expected_val
    return actual_val == expected_val


def _compare(rows: list[dict], expect: dict, invariants: list[str] | None = None) -> tuple[bool, str]:
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
        if not _values_equal(actual_val, expected_val):
            mismatches.append(f"{col}: 期待={expected_val!r} 実測={actual_val!r}")

    for expr in invariants or []:
        try:
            resolved_expr = invariant_eval.substitute_db_placeholders(expr, row)
            ok = invariant_eval.evaluate(resolved_expr)
        except invariant_eval.InvariantError as e:
            mismatches.append(str(e))
            continue
        if not ok:
            mismatches.append(f"不変条件を満たしません: {expr}（実測を当てはめると: {resolved_expr}）")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""
