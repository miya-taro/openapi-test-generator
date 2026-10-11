"""Resolve a request key in one DB, then independently compare a second DB to the API.

Only copies used to query expectations are changed. The API receives the original
request, not the resolved identifiers. Cross-database reads require stable test data.
"""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import math

import psycopg2

from config_loader import get_postgres_config, get_influxdb_config
from db_backends import postgres_backend as pg, influx_response as influx
from src.db_lookup import validate_lookup

MAX_LOOKUP_ROWS = 1000


def _config(config, lookup):
    engine = lookup["engine"]
    result = dict(get_postgres_config(config) if engine == "postgres" else get_influxdb_config(config))
    if lookup.get("database"):
        result["dbname" if engine == "postgres" else "database"] = lookup["database"]
    return result


def _read_values(config, lookup, value):
    if value is None or isinstance(value, (dict, list)) or not isinstance(value, (str, bool, int, float)):
        raise pg.DBResponseCheckError("別DB参照の送信値は文字列・有限数値・booleanで指定してください")
    if isinstance(value, float) and not math.isfinite(value):
        raise pg.DBResponseCheckError("別DB参照の送信値は有限数値で指定してください")
    db_config = _config(config, lookup)
    if lookup["engine"] == "postgres":
        conn = psycopg2.connect(**db_config)
        try:
            conn.set_session(readonly=True)
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT {pg._quote_ident(lookup["value_column"])} FROM {pg._quote_ident(lookup["table"])} '
                    f'WHERE {pg._quote_ident(lookup["match_column"])} = %s LIMIT %s',
                    (value, MAX_LOOKUP_ROWS + 1),
                )
                return [row[0] for row in cursor.fetchall()]
        finally:
            conn.rollback()
            conn.close()
    with influx._client(db_config) as client:
        influx._validate_columns(client, lookup["table"], [lookup["match_column"], lookup["value_column"]])
        rows = influx._select(client, lookup["table"], [(lookup["match_column"], "=", value)], MAX_LOOKUP_ROWS + 1)
        return [row.get(lookup["value_column"]) for row in rows]


def _convert(value, kind):
    if value is None or isinstance(value, (dict, list)):
        raise pg.DBResponseCheckUnverified("参照結果にnullまたは複合値があります。検索キーとして利用できません")
    try:
        if kind == "string":
            result = str(value).lower() if isinstance(value, bool) else str(value)
        elif kind in {"integer", "number"}:
            if isinstance(value, bool):
                raise ValueError("boolean is not a number")
            decimal = Decimal(str(value))
            if not decimal.is_finite() or kind == "integer" and decimal != decimal.to_integral_value():
                raise ValueError("not an exact finite number")
            result = int(decimal) if kind == "integer" else float(decimal)
        elif kind == "boolean":
            if type(value) is bool:
                result = value
            elif isinstance(value, str) and value.lower() in {"true", "false"}:
                result = value.lower() == "true"
            else:
                raise ValueError("not boolean")
        else:
            result = value
        if not isinstance(result, (str, int, float, bool)) or isinstance(result, float) and not math.isfinite(result):
            raise ValueError("unsupported key type")
        return result
    except (ValueError, ArithmeticError) as exc:
        raise pg.DBResponseCheckUnverified("取得値を指定した型へ変換できません。型の設定を確認してください") from exc


def prepare(check, config, query, path, body, evidence):
    sources = {"body": deepcopy(body or {}), "query": dict(query or {}), "path": dict(path or {})}
    original = deepcopy(sources)
    filters, empty_rules = [], []
    for item in check.filters:
        if not item.lookup or item.parameter not in original[item.source]:
            if item.lookup and item.source == "body":
                evidence.append({"parameter": f"body.{item.parameter}", "definition": item.lookup,
                                 "verdict": "対象外（API項目を省略）"})
            filters.append(item)
            continue
        lookup = validate_lookup(item.lookup, item.operator, item.auto)
        record = {"parameter": f"{item.source}.{item.parameter}", "definition": lookup,
                  "input_value": original[item.source][item.parameter], "target_column": item.column,
                  "verdict": "未確認"}
        evidence.append(record)
        values = _read_values(config, lookup, original[item.source][item.parameter])
        record["matched_rows"] = len(values)
        if len(values) > MAX_LOOKUP_ROWS:
            raise pg.DBResponseCheckUnverified(f"参照結果が{MAX_LOOKUP_ROWS}件を超えています。先頭の一部だけで照合しません")
        if not values:
            policy = lookup["on_empty"]
            if policy == "unverified":
                raise pg.DBResponseCheckUnverified(f"{item.parameter}の参照結果が0件です。0件時の期待動作は未設定です")
            if item.group and any(f is not item and f.group == item.group and f.parameter in original[f.source] for f in check.filters):
                raise pg.DBResponseCheckUnverified("参照0件と他のOR条件が同時に指定されています。個別ケースで期待動作を設定してください")
            if policy == "empty" and check.array_path is None:
                raise pg.DBResponseCheckError("0件時の空結果照合にはレスポンス配列の設定が必要です")
            empty_rules.append(lookup.get("empty_status") if policy == "status" else None)
            record.update(verdict="0件時の設定を適用", values=[])
            continue
        if lookup["cardinality"] == "one" and len(values) != 1:
            raise pg.DBResponseCheckUnverified(f"{item.parameter}の参照結果が複数件です。1件を要求する設定のため自動選択しません")
        converted = [_convert(value, lookup.get("value_type", "as_is")) for value in values]
        unique = list(dict.fromkeys(converted))
        resolved = unique[0] if lookup["cardinality"] == "one" else unique
        sources[item.source][item.parameter] = resolved
        filters.append(replace(item, lookup=None))
        record.update(verdict="取得済み", values=unique, comparison_value=resolved)
    if empty_rules:
        if len(set(empty_rules)) != 1:
            raise pg.DBResponseCheckUnverified("複数の参照0件条件で期待動作が異なります。個別ケースにしてください")
        return pg.PreparedDBResponse(dict(query or {}), dict(path or {}), []), empty_rules[0]
    resolved_check = replace(check, filters=filters)
    backend = pg if check.engine == "postgres" else influx
    target_config = get_postgres_config(config) if check.engine == "postgres" else get_influxdb_config(config)
    prepared = backend.prepare_db_response_check(resolved_check, target_config, sources["query"], sources["path"], sources["body"])
    for item in check.filters:
        if item.lookup and item.source in {"query", "path"} and item.parameter in original[item.source]:
            target = prepared.query_params if item.source == "query" else prepared.path_params
            target[item.parameter] = original[item.source][item.parameter]
    return prepared, None
