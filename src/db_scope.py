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
        if not isinstance(scope, dict) or set(scope) - {"table", "columns", "where"}:
            raise ValueError("DB比較範囲はtable・columns・whereで指定してください")
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
