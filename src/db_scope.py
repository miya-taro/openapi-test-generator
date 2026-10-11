"""Explicit, validated scopes for automatically generated error cases."""
import math
import re

KEY = "x-otg-error-db-unchanged"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_scopes(scopes):
    if not isinstance(scopes, list):
        raise ValueError("異常系のDB比較範囲は配列にしてください")
    def identifier(value):
        return isinstance(value, str) and IDENTIFIER.fullmatch(value)
    for scope in scopes:
        if not isinstance(scope, dict) or set(scope) - {"table", "columns", "where", "engine", "time_start", "time_end"}:
            raise ValueError("DB比較範囲にはtable・columns・where・engine・time_start・time_endを指定できます")
        engine = scope.get("engine", "postgres")
        if not isinstance(engine, str) or engine not in {"postgres", "influxdb"}:
            raise ValueError("対応DBはpostgresまたはinfluxdbです")
        if engine == "influxdb":
            from rfc3339_validator import validate_rfc3339
            from datetime import datetime
            for key in ("time_start", "time_end"):
                value = scope.get(key)
                if not isinstance(value, str) or not validate_rfc3339(value.upper()):
                    raise ValueError("InfluxDBの比較には開始・終了の日時（タイムゾーン付き）が必要です")
            # Preserve nanoseconds when checking the interval.
            def instant(value):
                from decimal import Decimal
                fraction = re.search(r"\.(\d+)", value)
                parsed = datetime.fromisoformat(re.sub(r"\.\d+", "", value.upper()).replace("Z", "+00:00"))
                return Decimal(int(parsed.timestamp())) + (Decimal("0." + fraction[1]) if fraction else 0)
            if instant(scope["time_start"]) > instant(scope["time_end"]):
                raise ValueError("比較期間の開始は終了以前にしてください")
            if isinstance(scope.get("where", {}), dict) and any(v is None for v in scope.get("where", {}).values()):
                raise ValueError("InfluxDBの行条件ではnullを指定できません")
        elif scope.get("time_start") is not None or scope.get("time_end") is not None:
            raise ValueError("期間の専用設定はInfluxDBのみ対応しています")
        if not identifier(scope.get("table")):
            raise ValueError("DBテーブル名は英字・数字・_で指定してください")
        columns = scope.get("columns")
        if not isinstance(columns, list) or not columns or not all(identifier(c) for c in columns) or len(set(columns)) != len(columns):
            raise ValueError("比較するDB列を重複なしで指定してください")
        where = scope.get("where", {})
        if not isinstance(where, dict) or not all(identifier(k) for k in where):
            raise ValueError("DB行条件は列名と値のJSONオブジェクトにしてください")
        if any(v is not None and not isinstance(v, (str, int, float, bool)) for v in where.values()):
            raise ValueError("DB行条件の値は文字列・数値・boolean・nullにしてください")
        if any(isinstance(v, float) and not math.isfinite(v) for v in where.values()):
            raise ValueError("DB行条件の数値は有限値にしてください")
    return scopes


def scopes_for_case(api, case):
    operation = ((api or {}).get("paths", {}).get(case.path, {}).get(case.method.lower()) or {})
    status = str(case.expected_status).strip().lower()
    is_error = status == "4xx" or all(re.fullmatch(r"4\d\d", part) for part in status.split("/"))
    return validate_scopes(operation.get(KEY, [])) if is_error else []
