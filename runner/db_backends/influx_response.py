"""Read-only InfluxQL 1.x response and before/after comparisons.

InfluxQL evaluates filters. Only explicitly mapped fields are compared; no schema or
business-rule inference. Bounded queries never silently truncate expected results.
"""
from contextlib import contextmanager
from collections import defaultdict
from dataclasses import asdict
import math

from influxdb import InfluxDBClient
from rfc3339_validator import validate_rfc3339

from db_backends.influx_backend import _quote_ident, _escape_value
from db_backends.postgres_backend import (
    DBResponseCheckError, DBResponseCheckUnverified, PreparedDBResponse,
)
from src.db_scope import validate_scopes

MAX_POINTS = 5000


class InfluxTimestamp(str):
    """A DB time value; compare as an instant without losing nanoseconds."""


@contextmanager
def _client(config):
    client = InfluxDBClient(
        host=config["host"], port=config["port"], database=config["database"],
        username=config.get("username"), password=config.get("password"),
        ssl=config.get("ssl", False), verify_ssl=True, timeout=30, retries=1,
    )
    try:
        yield client
    finally:
        client.close()


def _literal(value, column):
    if column == "time":
        if not isinstance(value, str) or not validate_rfc3339(value.upper()):
            raise DBResponseCheckError("timeの条件にはタイムゾーン付き日時を指定してください")
    if isinstance(value, str):
        return "'" + _escape_value(value) + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value)
    raise DBResponseCheckError("InfluxDBの条件値は文字列・有限数値・booleanにしてください（null不可）")


def _clause(spec):
    column, operator, value = spec[:3]
    quoted = _quote_ident(column)
    if operator == "in":
        if not isinstance(value, list):
            raise DBResponseCheckError("IN条件には配列を指定してください")
        if not value:
            # A valid impossible time interval, independent of field null semantics.
            return '(time < 0 AND time >= 0)'
        return '(' + ' OR '.join(f"{quoted} = {_literal(item, column)}" for item in value) + ')'
    if operator not in {"=", "!=", ">", ">=", "<", "<="}:
        raise DBResponseCheckError("未対応のInfluxDB比較条件です")
    return f"{quoted} {operator} {_literal(value, column)}"


def _where(specs):
    groups = defaultdict(list)
    clauses = []
    for spec in specs:
        group = spec[3] if len(spec) > 3 else None
        if group:
            groups[group].append(_clause(spec))
        else:
            clauses.append(_clause(spec))
    clauses.extend('(' + ' OR '.join(items) + ')' for items in groups.values())
    return ' AND '.join(clauses)


def _select(client, table, specs, limit=MAX_POINTS + 1):
    query = f"SELECT * FROM {_quote_ident(table)}"
    where = _where(specs)
    if where:
        query += " WHERE " + where
    query += f" ORDER BY time ASC LIMIT {int(limit)}"
    # LIMIT may apply per series. Stop collecting at the total bound as well.
    rows = []
    for point in client.query(query).get_points():
        rows.append(point)
        if len(rows) >= limit:
            break
    return rows


def _validate_columns(client, table, columns):
    fields = {p["fieldKey"] for p in client.query(f"SHOW FIELD KEYS FROM {_quote_ident(table)}").get_points()}
    tags = {p["tagKey"] for p in client.query(f"SHOW TAG KEYS FROM {_quote_ident(table)}").get_points()}
    if not fields:
        raise DBResponseCheckUnverified("measurementのフィールド定義がありません。対象名・DB・試験データを確認してください")
    missing = set(columns) - fields - tags - {"time"}
    if missing:
        raise DBResponseCheckError(f"未定義のInfluxDB項目: {', '.join(sorted(missing))}")


def _bounded(rows):
    if len(rows) > MAX_POINTS:
        raise DBResponseCheckUnverified(f"照合対象が{MAX_POINTS}ポイントを超えています。期間・タグで範囲を限定してください")
    return rows


def _coverage(client, table, filters, specs, count):
    coverage, checked = [], set()
    for index, item in enumerate(filters):
        members = [i for i, f in enumerate(filters) if item.group and f.group == item.group] if item.group else [index]
        others = [s for i, s in enumerate(specs) if i not in members]
        label = f"{item.source}.{item.parameter}"
        unit = item.group or f"__{index}"
        if unit not in checked:
            if len(_select(client, table, others, count + 1)) <= count:
                raise DBResponseCheckUnverified(f"既存データではAPI条件「{label}」の省略を検出できません")
            checked.add(unit)
        branches = [specs[i][:3] for i in members if i != index]

        def witness(required, branches=branches, others=others):
            exclusions = []
            for column, op, value in branches:
                if op == "in":
                    exclusions.extend((column, "!=", v) for v in value)
                else:
                    exclusions.append((column, {"=": "!=", ">": "<=", ">=": "<", "<": ">=", "<=": ">"}[op], value))
            return bool(_select(client, table, [*others, required, *exclusions], 1))

        if branches and not witness(specs[index][:3]):
            raise DBResponseCheckUnverified(f"API条件「{label}」だけで一致するOR分岐の試験データがありません")
        boundary = item.operator in {">", ">=", "<", "<="}
        if boundary and not witness((item.column, "=", specs[index][2])):
            raise DBResponseCheckUnverified(f"API条件「{label}」の境界と一致するポイントがありません")
        values = []
        if item.operator == "in":
            for value in specs[index][2]:
                if value in values:
                    continue
                if not witness((item.column, "=", value)):
                    raise DBResponseCheckUnverified(f"API条件「{label}」のIN指定値に一致するポイントがありません")
                values.append(value)
        coverage.append({"parameter": label, "omission_detectable": True,
                         "or_branch_detectable": bool(branches), "boundary_present": boundary,
                         "in_members_present": values})
    return coverage


def prepare_db_response_check(check, config, query_params, path_params, body=None):
    query, path = dict(query_params or {}), dict(path_params or {})
    body = body or {}
    filters = [f for f in check.filters if f.source != "body" or f.parameter in body]
    specs, automatic = [], []
    for item in filters:
        if item.auto:
            if item.group or item.operator == "in" or item.source == "body":
                raise DBResponseCheckError("OR・IN・Bodyの検索値は明示してください")
            automatic.append(item)
            continue
        source = {"body": body, "query": query, "path": path}[item.source]
        if item.parameter not in source:
            raise DBResponseCheckUnverified(f"APIパラメータ「{item.parameter}」の値がありません")
        specs.append((item.column, item.operator, source[item.parameter], item.group))
    with _client(config) as client:
        _validate_columns(client, check.table, [*check.fields.values(), *(f.column for f in filters)])
        if automatic:
            candidates = _bounded(_select(client, check.table, specs))
            for item in automatic:
                from response_check import _datetime_instant
                values = sorted({p[item.column] for p in candidates if p.get(item.column) is not None},
                                key=_datetime_instant if item.column == "time" else None)
                peers = [f for f in automatic if f.column == item.column]
                both = any(f.operator in {">", ">="} for f in peers) and any(f.operator in {"<", "<="} for f in peers)
                if len(values) < (4 if both else 2):
                    raise DBResponseCheckUnverified(f"DB項目「{item.column}」に境界を確かめるデータが足りません")
                value = values[-2] if item.operator in {"<", "<="} else values[1]
                target = query if item.source == "query" else path
                target[item.parameter] = value
        specs = [(f.column, f.operator, {"body": body, "query": query, "path": path}[f.source][f.parameter], f.group) for f in filters]
        rows = _bounded(_select(client, check.table, specs))
        coverage = _coverage(client, check.table, filters, specs, len(rows))
        expected = [{key: InfluxTimestamp(row[column]) if column == "time" else row.get(column)
                     for key, column in check.fields.items()} for row in rows]
        return PreparedDBResponse(query, path, expected, coverage)


def snapshot_rows(config, scope):
    validate_scopes([asdict(scope)])
    specs = [(column, "=", value) for column, value in scope.where.items()]
    specs.extend([("time", ">=", scope.time_start), ("time", "<=", scope.time_end)])
    with _client(config) as client:
        _validate_columns(client, scope.table, [*scope.columns, *scope.where])
        rows = _bounded(_select(client, scope.table, specs))
    return [{column: row.get(column) for column in scope.columns} for row in rows]
