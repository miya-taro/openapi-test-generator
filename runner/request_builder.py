from __future__ import annotations
import json
from urllib.parse import urlencode
from models import RunCase

OMIT_MARKERS = {"（省略）", "（フィールドを省略）"}
EMPTY_VALUE_MARKER = "（空文字）"
NULL_VALUE_MARKER = "null"

# ルートbody（paramName == "requestBody"）向けのプレースホルダ値。
# openapi-test-gen の src/generator/rules/object.py が出力する値と対応させている。
_ROOT_BODY_EMPTY_MARKER = "{}"
_ROOT_BODY_EXTRA_PROP_MARKER = '{ ...validBody, "__extra__": "value" }'

FORMAT_SAMPLES: dict[str, str | int | bool] = {
    "email": "test@example.com",
    "date": "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "uri": "https://example.com",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "hostname": "example.com",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
}


def build_url(base_url: str, case: RunCase) -> str:
    path = case.path
    if case.param_in == "path" and case.input_value not in OMIT_MARKERS:
        val = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        path = path.replace("{" + case.param_name + "}", val)

    url = base_url.rstrip("/") + path

    if case.param_in == "query" and case.input_value not in OMIT_MARKERS:
        val = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        url += "?" + urlencode({case.param_name: val})

    return url


def build_body_args(case: RunCase, openapi: dict | None) -> list[str]:
    if case.param_in != "body":
        return []

    body = _build_body(case, openapi)
    return ["-d", json.dumps(body, ensure_ascii=False)]


def _build_body(case: RunCase, openapi: dict | None) -> dict:
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi) if openapi else None

    # ベースライン: required フィールドを（ネスト・配列要素も含めて）全階層分、有効な値で埋めた body
    baseline = _expand_value(schema) if schema is not None else {}
    body: dict = baseline if isinstance(baseline, dict) else {}

    # ルートbody全体を対象とするケース（空body / additionalProperties）は body 全体を差し替える
    if case.param_name == "requestBody":
        if case.input_value == _ROOT_BODY_EMPTY_MARKER:
            return {}
        if case.input_value == _ROOT_BODY_EXTRA_PROP_MARKER:
            return {**body, "__extra__": "value"}
        return body

    if case.input_value in OMIT_MARKERS:
        _delete_nested(body, case.param_name, schema)
    elif case.input_value == NULL_VALUE_MARKER:
        _set_nested(body, case.param_name, None, schema)
    else:
        raw = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        field_schema = _resolve_nested_schema(schema, case.param_name) if schema is not None else {}
        _set_nested(body, case.param_name, _coerce_value(raw, field_schema), schema)

    return body


def _navigate_to_parent(body: dict, dotted_path: str, root_schema: dict | None) -> tuple[dict, str]:
    """ドット区切りパスの最終セグメント手前まで辿り、(親コンテナ, 最終キー) を返す。

    セグメントが "lines[]" のように "[]" で終わる場合は配列として扱い、
    先頭要素（存在しなければ新規作成した空dict）に読み替える。
    途中のコンテナが存在しない場合（親フィールドが required でない等）は、
    スキーマから有効なベースライン値を生成して埋める
    （そうしないと、そのコンテナの他の required フィールドが欠けたリクエストになってしまう）。
    """
    parts = dotted_path.split(".")
    container = body
    schema_node: dict | None = root_schema
    for part in parts[:-1]:
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part

        props = schema_node.get("properties", {}) if isinstance(schema_node, dict) else {}
        field_schema = props.get(key) if isinstance(props, dict) else None

        if is_array:
            item_schema = field_schema.get("items") if isinstance(field_schema, dict) else None
            lst = container.get(key)
            if not isinstance(lst, list) or not lst or not isinstance(lst[0], dict):
                seed = _expand_value(item_schema) if isinstance(item_schema, dict) else {}
                lst = [seed if isinstance(seed, dict) else {}]
                container[key] = lst
            container = lst[0]
            schema_node = item_schema
        else:
            nxt = container.get(key)
            if not isinstance(nxt, dict):
                seed = _expand_value(field_schema) if isinstance(field_schema, dict) else {}
                nxt = seed if isinstance(seed, dict) else {}
                container[key] = nxt
            container = nxt
            schema_node = field_schema
    last = parts[-1]
    last_key = last[:-2] if last.endswith("[]") else last
    return container, last_key


def _set_nested(body: dict, dotted_path: str, value: object, root_schema: dict | None) -> None:
    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    container[key] = value


def _delete_nested(body: dict, dotted_path: str, root_schema: dict | None) -> None:
    container, key = _navigate_to_parent(body, dotted_path, root_schema)
    container.pop(key, None)


def _resolve_nested_schema(root_schema: dict | None, dotted_path: str) -> dict:
    """ドット区切りパス（配列要素を表す "[]" 区切りを含む）からフィールドのスキーマを解決する。"""
    if root_schema is None:
        return {}
    node: dict = root_schema
    for part in dotted_path.split("."):
        is_array = part.endswith("[]")
        key = part[:-2] if is_array else part
        props = node.get("properties", {}) if isinstance(node, dict) else {}
        node = props.get(key)
        if not isinstance(node, dict):
            return {}
        if is_array:
            node = node.get("items", {})
            if not isinstance(node, dict):
                return {}
    return node


def _resolve_request_body_schema(operation_id: str, path: str, method: str, openapi: dict) -> dict | None:
    paths = openapi.get("paths", {})
    path_item = paths.get(path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, operation_id)
    if path_item is None:
        return None

    op = path_item.get(method.lower())
    if op is None:
        return None

    rb = op.get("requestBody", {})
    content = rb.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    return _resolve_ref(schema, openapi) if schema else None


def _find_path_by_operation_id(paths: dict, operation_id: str) -> dict | None:
    for path_item in paths.values():
        for method_item in path_item.values():
            if isinstance(method_item, dict) and method_item.get("operationId") == operation_id:
                return path_item
    return None


def _resolve_ref(schema: dict, openapi: dict) -> dict:
    if "$ref" not in schema:
        return schema
    ref = schema["$ref"]
    parts = ref.lstrip("#/").split("/")
    node = openapi
    for part in parts:
        node = node.get(part, {})
    return node


def _expand_value(schema: dict) -> object:
    t = schema.get("type", "string")
    fmt = schema.get("format", "")
    enum = schema.get("enum")

    if enum:
        return enum[0]

    if t == "integer" or t == "number":
        minimum = schema.get("minimum")
        return minimum if minimum is not None else 1

    if t == "boolean":
        return True

    if t == "array":
        items = schema.get("items", {})
        return [_expand_value(items)]

    if t == "object":
        props = schema.get("properties", {})
        required = schema.get("required", [])
        return {k: _expand_value(props[k]) for k in required if k in props}

    # string
    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len

    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]

    return "test"


def _coerce_value(raw_value: str, field_schema: dict) -> object:
    t = field_schema.get("type", "string")
    if t in ("integer", "number"):
        try:
            return int(raw_value) if t == "integer" else float(raw_value)
        except ValueError:
            pass
    if t == "boolean":
        return raw_value.lower() in ("true", "1", "yes")
    return raw_value
