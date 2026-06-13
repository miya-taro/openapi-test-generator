from __future__ import annotations
import json
from urllib.parse import urlencode
from models import RunCase

OMIT_MARKERS = {"（省略）", "（フィールドを省略）"}
EMPTY_VALUE_MARKER = "（空文字）"

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
    body: dict = {}

    if openapi is not None:
        baseline = _generate_baseline(case, openapi)
        body.update(baseline)

    if case.input_value not in OMIT_MARKERS:
        raw = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
        body[case.param_name] = _coerce_value(case.param_name, raw, openapi, case)

    return body


def _generate_baseline(case: RunCase, openapi: dict) -> dict:
    schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi)
    if schema is None:
        return {}
    required = schema.get("required", [])
    props = schema.get("properties", {})
    result: dict = {}
    for field_name in required:
        if field_name == case.param_name:
            continue
        field_schema = props.get(field_name, {})
        result[field_name] = _expand_value(field_schema)
    return result


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
        required = schema.get("required", list(props.keys()))
        return {k: _expand_value(props[k]) for k in required if k in props}

    # string
    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len

    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]

    return "test"


def _coerce_value(field_name: str, raw_value: str, openapi: dict | None, case: RunCase) -> object:
    if openapi is not None:
        schema = _resolve_request_body_schema(case.operation_id, case.path, case.method, openapi)
        if schema:
            props = schema.get("properties", {})
            field_schema = props.get(field_name, {})
            t = field_schema.get("type", "string")
            if t in ("integer", "number"):
                try:
                    return int(raw_value) if t == "integer" else float(raw_value)
                except ValueError:
                    pass
            if t == "boolean":
                return raw_value.lower() in ("true", "1", "yes")
    return raw_value
