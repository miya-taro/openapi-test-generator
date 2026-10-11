"""Validate explicit lookup relationships; no database or business-rule inference."""
import re

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
KEYS = {"engine", "database", "table", "match_column", "value_column", "cardinality",
        "value_type", "on_empty", "empty_status"}


def validate_lookup(value, operator, auto):
    if not isinstance(value, dict) or set(value) - KEYS:
        raise ValueError("別DB参照の設定項目が不正です")
    if value.get("engine") not in {"postgres", "influxdb"}:
        raise ValueError("参照元DBはpostgresまたはinfluxdbを指定してください")
    for key in ("table", "match_column", "value_column"):
        if not isinstance(value.get(key), str) or not IDENT.fullmatch(value[key]):
            raise ValueError(f"別DB参照の{key}には英数字・アンダースコアの名前を指定してください")
    if "database" in value and (not isinstance(value["database"], str) or not value["database"].strip()):
        raise ValueError("参照DB名は空でない文字列にしてください")
    if value.get("cardinality") not in {"one", "many"}:
        raise ValueError("参照結果を1件とするか、全件使うか指定してください")
    if operator != ("=" if value["cardinality"] == "one" else "in") or auto:
        raise ValueError("別DB参照は送信値の明示が必要です。1件は=、全件はinで比較してください")
    if value.get("value_type", "as_is") not in {"as_is", "string", "integer", "number", "boolean"}:
        raise ValueError("取得値の変換型が不正です")
    if value.get("on_empty") not in {"unverified", "empty", "status"}:
        raise ValueError("参照結果が0件の場合の扱いを指定してください")
    status = value.get("empty_status")
    if value["on_empty"] == "status":
        if type(status) is not int or not 400 <= status <= 499:
            raise ValueError("参照結果0件の期待statusは400〜499で指定してください")
    elif status is not None:
        raise ValueError("期待statusは0件時にエラーを期待する場合のみ指定してください")
    return dict(value)
