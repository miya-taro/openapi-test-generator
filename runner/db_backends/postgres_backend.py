"""DBシナリオの db_check（engine: postgres）を実行・検証する。"""
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras
from psycopg2.extensions import ISOLATION_LEVEL_REPEATABLE_READ

from db_backends import invariant_eval

_IDENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILTER_OPERATORS = {"=", ">", ">=", "<", "<="}
_MAX_RESPONSE_ROWS = 5000


class DBResponseCheckUnverified(Exception):
    """The database does not contain enough representative rows to prove the rule."""


class DBResponseCheckError(Exception):
    """The response-to-database mapping cannot be executed safely."""


@dataclass
class PreparedDBResponse:
    query_params: dict
    path_params: dict
    expected_rows: list[dict]


def prepare_db_response_check(db_response_check, db_config: dict, query_params: dict, path_params: dict) -> PreparedDBResponse:
    """Choose API filter values from existing rows and derive the exact expected result.

    This path is deliberately read-only: it never inserts or changes rows. Automatic range
    filters select interior values from the existing column values so the request has rows on
    the boundary and rows outside the range to distinguish a real filter from an unfiltered API.
    """
    table = _quote_ident(db_response_check.table)
    columns = list(dict.fromkeys(db_response_check.fields.values()))
    if not columns:
        raise DBResponseCheckError("db_response_check.fields にDBカラムがありません")
    for column in columns:
        _quote_ident(column)

    filters = []
    seen_names = set()
    for item in db_response_check.filters:
        if item.operator not in _FILTER_OPERATORS:
            raise DBResponseCheckError(f"未対応の比較条件です: {item.operator!r}")
        if item.source not in {"query", "path"}:
            raise DBResponseCheckError(f"未対応のAPIパラメータ種別です: {item.source!r}")
        _quote_ident(item.column)
        name_key = (item.source, item.parameter)
        if name_key in seen_names:
            raise DBResponseCheckError(f"APIパラメータの対応が重複しています: {item.source}.{item.parameter}")
        seen_names.add(name_key)
        filters.append(item)

    effective_query = dict(query_params or {})
    effective_path = dict(path_params or {})
    filter_values: list[object | None] = [None] * len(filters)
    auto_by_column: dict[tuple[str, str | None], list[int]] = defaultdict(list)

    for index, item in enumerate(filters):
        if item.auto:
            auto_by_column[(item.column, item.parameter_format)].append(index)
            continue
        source = effective_query if item.source == "query" else effective_path
        if item.parameter not in source:
            raise DBResponseCheckUnverified(
                f"APIパラメータ「{item.parameter}」の値がありません。自動生成にするか値を指定してください"
            )
        filter_values[index] = source[item.parameter]

    conn = psycopg2.connect(**db_config)
    try:
        conn.set_session(isolation_level=ISOLATION_LEVEL_REPEATABLE_READ, readonly=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Fixed filters narrow the rows from which automatic boundary values are selected.
            fixed_specs = [
                (item.column, item.operator, filter_values[index])
                for index, item in enumerate(filters) if not item.auto
            ]
            for (column, parameter_format), indexes in auto_by_column.items():
                asc_values = _distinct_edge_values(
                    cur, table, column, fixed_specs, ascending=True, parameter_format=parameter_format
                )
                desc_values = _distinct_edge_values(
                    cur, table, column, fixed_specs, ascending=False, parameter_format=parameter_format
                )
                distinct_values = []
                for value in [*asc_values, *reversed(desc_values)]:
                    if value not in distinct_values:
                        distinct_values.append(value)

                group = [filters[index] for index in indexes]
                has_lower = any(item.operator in {">", ">="} for item in group)
                has_upper = any(item.operator in {"<", "<="} for item in group)
                if has_lower and has_upper:
                    if len(distinct_values) < 4 or len(asc_values) < 2 or len(desc_values) < 2:
                        raise DBResponseCheckUnverified(
                            f"DB列「{column}」に期間検索を確かめる異なる値が4件以上ありません"
                        )
                    lower_value = asc_values[1]
                    upper_value = desc_values[1]
                    if lower_value >= upper_value:
                        raise DBResponseCheckUnverified(
                            f"DB列「{column}」に開始・終了の両方を試せる期間データがありません"
                        )
                else:
                    if len(distinct_values) < 2:
                        raise DBResponseCheckUnverified(
                            f"DB列「{column}」に検索条件の境界を確かめる異なる値が2件以上ありません"
                        )
                    lower_value = asc_values[1] if len(asc_values) >= 2 else distinct_values[1]
                    upper_value = desc_values[1] if len(desc_values) >= 2 else distinct_values[-2]

                for index in indexes:
                    item = filters[index]
                    if item.operator in {">", ">="}:
                        value = lower_value
                    elif item.operator in {"<", "<="}:
                        value = upper_value
                    else:  # Equality selects a value that is known to have a different neighbor.
                        value = asc_values[1] if len(asc_values) >= 2 else distinct_values[1]
                    if parameter_format == "date-time" and isinstance(value, date) and not isinstance(value, datetime):
                        raise DBResponseCheckUnverified(
                            f"DB列「{column}」は日付のみの値です。date-time Queryに使う時刻・タイムゾーンを定義できません"
                        )
                    if parameter_format == "date" and isinstance(value, datetime):
                        value = value.date()
                    filter_values[index] = value
                    target = effective_query if item.source == "query" else effective_path
                    target[item.parameter] = _request_value(value, parameter_format)

            if any(value is None for value in filter_values):
                raise DBResponseCheckError("検索条件の値を解決できませんでした")

            specs = [
                (item.column, item.operator, filter_values[index])
                for index, item in enumerate(filters)
            ]
            select_sql = ", ".join(_quote_ident(column) for column in columns)
            sql, params = _build_mapped_select(table, select_sql, specs, _MAX_RESPONSE_ROWS + 1)
            cur.execute(sql, params)
            rows = [dict(row) for row in cur.fetchall()]
            if len(rows) > _MAX_RESPONSE_ROWS:
                raise DBResponseCheckUnverified(
                    f"照合対象が{_MAX_RESPONSE_ROWS}件を超えるため、自動照合できません"
                )
            if not rows and filters:
                raise DBResponseCheckUnverified("指定した検索条件に一致するDB行がありません")

            # Prove every configured condition changes the result and has a row exactly at its
            # boundary. Without these, a passing response could be an unfiltered/static result.
            for index, item in enumerate(filters):
                without_one = [spec for position, spec in enumerate(specs) if position != index]
                if _has_more_rows(cur, table, without_one, len(rows)):
                    boundary_specs = [*without_one, (item.column, "=", filter_values[index])]
                    if not _has_any_row(cur, table, boundary_specs):
                        raise DBResponseCheckUnverified(
                            f"DB列「{item.column}」にAPI条件「{item.parameter}」の境界値と一致する行がありません"
                        )
                else:
                    raise DBResponseCheckUnverified(
                        f"既存データではAPI条件「{item.parameter}」が結果を絞り込むことを確かめられません"
                    )

            expected_rows = [
                {response_path: row[column] for response_path, column in db_response_check.fields.items()}
                for row in rows
            ]
            return PreparedDBResponse(effective_query, effective_path, expected_rows)
    finally:
        conn.rollback()
        conn.close()


def matching_primary_keys(db_config: dict, table: str, primary_key: str, where: dict) -> list[object]:
    """Return matching values for one explicitly configured, single-column primary key.

    This is used only by opt-in POST cleanup. The before/after difference lets the runner delete
    rows created by this request while preserving rows that already matched the same values.
    """
    table_ident = _quote_ident(table)
    primary_key_ident = _quote_ident(primary_key)
    if not where:
        raise DBResponseCheckError("POST後のクリーンアップには行特定用のDB列が必要です")
    for column in where:
        _quote_ident(column)

    conn = psycopg2.connect(**db_config)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT kcu.column_name FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
                "AND tc.table_name = kcu.table_name "
                "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' "
                "AND tc.table_name = %s ORDER BY kcu.ordinal_position",
                (table,),
            )
            key_columns = [row[0] for row in cur.fetchall()]
            if key_columns != [primary_key]:
                raise DBResponseCheckError(
                    f"{table}.{primary_key} が単一カラムの主キーではないため、行を安全に片付けられません"
                )

            conditions = []
            params = []
            for column, value in where.items():
                if value is None:
                    conditions.append(f"{_quote_ident(column)} IS NULL")
                else:
                    conditions.append(f"{_quote_ident(column)} = %s")
                    params.append(value)
            cur.execute(
                f"SELECT {primary_key_ident} FROM {table_ident} WHERE {' AND '.join(conditions)} LIMIT 101",
                params,
            )
            rows = cur.fetchall()
            if len(rows) > 100:
                raise DBResponseCheckError("行特定条件の一致が100件を超えるため、クリーンアップを中止しました")
            return [row[0] for row in rows]
    finally:
        conn.close()


def _distinct_edge_values(
    cur, table: str, column: str, fixed_specs: list[tuple], ascending: bool,
    parameter_format: str | None = None,
) -> list:
    order = "ASC" if ascending else "DESC"
    where, params = _where_sql(fixed_specs)
    column_ident = _quote_ident(column)
    value_expression = f"{column_ident}::date" if parameter_format == "date" else column_ident
    non_null = f"{column_ident} IS NOT NULL"
    if where:
        where = f"({where}) AND {non_null}"
    else:
        where = non_null
    cur.execute(
        f"SELECT DISTINCT {value_expression} AS value FROM {table} WHERE {where} "
        f"ORDER BY value {order} LIMIT 2",
        params,
    )
    return [row["value"] for row in cur.fetchall()]


def _where_sql(specs: list[tuple]) -> tuple[str, list]:
    if not specs:
        return "", []
    conditions = [f"{_quote_ident(column)} {operator} %s" for column, operator, _value in specs]
    return " AND ".join(conditions), [value for _column, _operator, value in specs]


def _build_mapped_select(table: str, select_sql: str, specs: list[tuple], limit: int | None = None) -> tuple[str, list]:
    where, params = _where_sql(specs)
    sql = f"SELECT {select_sql} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    return sql, params


def _has_more_rows(cur, table: str, specs: list[tuple], count: int) -> bool:
    where, params = _where_sql(specs)
    sql = f"SELECT 1 FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += " LIMIT %s"
    cur.execute(sql, [*params, count + 1])
    return len(cur.fetchall()) > count


def _has_any_row(cur, table: str, specs: list[tuple]) -> bool:
    where, params = _where_sql(specs)
    sql = f"SELECT 1 FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += " LIMIT 1"
    cur.execute(sql, params)
    return cur.fetchone() is not None


def _request_value(value, parameter_format: str | None = None):
    if parameter_format == "date" and isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value) if value is not None else value


def check(db_check, db_config: dict, evidence: dict | None = None) -> tuple[bool, str]:
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

    if evidence is not None:
        evidence["table"] = db_check.table
        evidence["where"] = db_check.where
        evidence["expected"] = db_check.expect
        evidence["actual_rows"] = [dict(row) for row in rows]
    return _compare(rows, db_check.expect, db_check.invariants)


def matching_row_count(db_config: dict, table: str, where: dict | None = None) -> int:
    """Count matching rows before a POST so a pre-existing row cannot produce a false pass."""
    table_ident = _quote_ident(table)
    conditions = []
    params = []
    for column, value in (where or {}).items():
        column_ident = _quote_ident(column)
        if value is None:
            conditions.append(f"{column_ident} IS NULL")
        else:
            conditions.append(f"{column_ident} = %s")
            params.append(value)
    conn = psycopg2.connect(**db_config)
    try:
        with conn.cursor() as cur:
            predicate = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            cur.execute(f"SELECT COUNT(*) FROM {table_ident}{predicate}", params)
            return int(cur.fetchone()[0])
    finally:
        conn.close()


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

    if len(rows) != 1:
        return False, f"対象行を1件に特定できません（実測={len(rows)}件）"

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
