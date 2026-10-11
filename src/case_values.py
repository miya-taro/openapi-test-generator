"""Lossless generated JSON values shared by generation and request assembly."""

import json

JSON_VALUE_PREFIX = "__JSON_VALUE__"


def encode_json_value(value):
    return JSON_VALUE_PREFIX + json.dumps(value, ensure_ascii=False, allow_nan=False)


def coerce_value(raw_value: str, field_schema: dict) -> object:
    if raw_value.startswith(JSON_VALUE_PREFIX):
        return json.loads(raw_value[len(JSON_VALUE_PREFIX) :])
    t = field_schema.get("type", "string")
    if isinstance(t, list):
        non_null_types = [value for value in t if value != "null"]
        t = non_null_types[0] if len(non_null_types) == 1 else None
    if t in ("integer", "number"):
        try:
            return int(raw_value) if t == "integer" else float(raw_value)
        except ValueError:
            pass
    if t == "boolean":
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            value = raw_value
        if isinstance(value, bool):
            return value
        # JSON-quoted strings such as "yes" are deliberately invalid boolean
        # inputs; only unquoted runner literals are coerced to boolean values.
        if (
            value == raw_value
            and isinstance(value, str)
            and value.lower() in ("true", "1", "yes")
        ):
            return True
        if (
            value == raw_value
            and isinstance(value, str)
            and value.lower() in ("false", "0", "no")
        ):
            return False
        return value
    if t in ("array", "object"):
        # generator（array.py/object.py/common.py）はこのフィールド自体が array/object 型の
        # 場合、inputValue に JSON リテラル文字列（例: '[{"a": 1}]' や '"not-an-array"'）を
        # 出力する。json.loads せずそのまま埋め込むと、リクエストボディの当該フィールドが
        # 「JSON配列/オブジェクト」ではなく「JSON文字列」になってしまい、意図と異なるテストに
        # なってしまう（境界値テストなのに型不正テストとして扱われる等）。
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            pass
    return raw_value
