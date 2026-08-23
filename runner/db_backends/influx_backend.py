"""DBシナリオの db_check（engine: influxdb, 1.x系/InfluxQL）を実行・検証する。"""
from __future__ import annotations
import re

from influxdb import InfluxDBClient

_IDENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DURATION_PATTERN = re.compile(r"^\d+(ns|u|µ|ms|s|m|h|d|w)$")
_DEFAULT_TIME_RANGE = "5m"


def check(db_check, db_config: dict) -> tuple[bool, str]:
    """db_check を実行し (適合したか, 詳細メッセージ) を返す。"""
    if not db_check.measurement:
        return False, "db_check に measurement の指定がありません"

    client = InfluxDBClient(
        host=db_config["host"],
        port=db_config["port"],
        username=db_config.get("username"),
        password=db_config.get("password"),
        database=db_config["database"],
    )
    try:
        query = _build_query(db_check)
        result = client.query(query)
        points = list(result.get_points())
    finally:
        client.close()

    return _compare(points, db_check.expect)


def _build_query(db_check) -> str:
    measurement = _quote_ident(db_check.measurement)

    conditions = []
    for tag, value in (db_check.tags or {}).items():
        conditions.append(f"{_quote_ident(tag)} = '{_escape_value(value)}'")

    time_range = db_check.time_range or _DEFAULT_TIME_RANGE
    if not _DURATION_PATTERN.match(time_range):
        raise ValueError(f"不正な time_range です: {time_range!r}（例: 5m, 1h, 30s）")
    conditions.append(f"time > now() - {time_range}")

    where_clause = " AND ".join(conditions)
    return f"SELECT * FROM {measurement} WHERE {where_clause} ORDER BY time DESC LIMIT 1"


def _quote_ident(name: str) -> str:
    if not _IDENT_PATTERN.match(name):
        raise ValueError(f"不正な識別子です: {name!r}")
    return f'"{name}"'


def _escape_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _compare(points: list[dict], expect: dict) -> tuple[bool, str]:
    exists_expected = expect.get("exists", True)

    if not exists_expected:
        if points:
            return False, f"存在しないはずのポイントが見つかりました: {points[0]}"
        return True, ""

    if not points:
        return False, "該当するポイントが見つかりません"

    fields = expect.get("fields") or {}
    point = points[0]
    mismatches = []
    for field_name, expected_val in fields.items():
        if field_name not in point:
            mismatches.append(f"{field_name}: フィールドが存在しません")
            continue
        actual_val = point[field_name]
        if actual_val != expected_val:
            mismatches.append(f"{field_name}: 期待={expected_val!r} 実測={actual_val!r}")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""
