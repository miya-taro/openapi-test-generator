"""object 型のルール（additionalProperties / 空 body）。"""
from __future__ import annotations

import json
from copy import deepcopy

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from ...schema_example import NoSchemaExample, find_schema_example
from .common import _get_invalid_value_for_type


def generate_object_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]
    additional_props = schema.get("additionalProperties")

    # additionalProperties: false — 未定義プロパティ追加（異常）
    if opts["includeAbnormal"] and additional_props is False:
        cases.append({
            "summary": f"{ctx['paramName']} 未定義プロパティ追加（異常）",
            "keyword": "additionalProperties",
            "perspective": "異常系_additionalProperties",
            "inputValue": '{ ...validBody, "__extra__": "value" }',
            "expectedStatus": "4xx",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "スキーマ外のキーを含む JSON",
        })

    # additionalProperties がスキーマ（型付きで追加プロパティを許可）の場合
    if isinstance(additional_props, dict):
        prop_type = additional_props.get("type")

        if opts["includeAbnormal"] and prop_type:
            invalid_value = _get_invalid_value_for_type(prop_type)
            if invalid_value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 未定義プロパティ追加・型不適合（異常）",
                    "keyword": "additionalProperties",
                    "perspective": "異常系_additionalProperties型不適合",
                    "inputValue": f'{{ ...validBody, "__extra__": {invalid_value} }}',
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "additionalProperties のスキーマに適合しない型の追加プロパティ",
                })

    # minProperties / maxProperties. Generate an actual JSON object with the exact
    # property count so both root and nested object constraints use the same cases.
    min_properties = schema.get("minProperties")
    if isinstance(min_properties, int) and not isinstance(min_properties, bool) and min_properties >= 0:
        value = _object_value_with_count(schema, min_properties)
        if opts["includeNormal"] and value is not None:
            cases.append({
                "summary": f"{ctx['paramName']} 最小項目数（正常）",
                "keyword": "minProperties",
                "perspective": "正常系_minProperties",
                "inputValue": json.dumps(value, ensure_ascii=False),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"] and min_properties > 0:
            value = _object_value_with_count(schema, min_properties - 1, ignore_keyword="minProperties")
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最小項目数-1（異常）",
                    "keyword": "minProperties",
                    "perspective": "異常系_minProperties未満",
                    "inputValue": json.dumps(value, ensure_ascii=False),
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "",
                })

    max_properties = schema.get("maxProperties")
    if isinstance(max_properties, int) and not isinstance(max_properties, bool) and max_properties >= 0:
        value = _object_value_with_count(schema, max_properties)
        if opts["includeNormal"] and value is not None:
            cases.append({
                "summary": f"{ctx['paramName']} 最大項目数（正常）",
                "keyword": "maxProperties",
                "perspective": "正常系_maxProperties",
                "inputValue": json.dumps(value, ensure_ascii=False),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"]:
            value = _object_value_with_count(schema, max_properties + 1, ignore_keyword="maxProperties")
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最大項目数+1（異常）",
                    "keyword": "maxProperties",
                    "perspective": "異常系_maxProperties超過",
                    "inputValue": json.dumps(value, ensure_ascii=False),
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "",
                })

    # 空 body（required プロパティが 1 件以上ある場合のみ）
    if opts["includeAbnormal"]:
        required = schema.get("required") or []
        if ctx.get("isRootBody") and len(required) > 0:
            cases.append({
                "summary": f"{ctx['paramName']} 空 body（異常）",
                "keyword": "required",
                "perspective": "異常系_空body",
                "inputValue": "{}",
                "expectedStatus": "4xx",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "required プロパティが存在するため空 body は不正",
            })

    return cases


def _object_value_with_count(
    schema: dict,
    count: int,
    ignore_keyword: str | None = None,
) -> dict | None:
    """Build a request object with exactly count properties, if the schema allows it."""
    if count < 0 or count > 1000:
        return None

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    additional = schema.get("additionalProperties", True)
    request_properties = {
        name: prop_schema
        for name, prop_schema in properties.items()
        if not (isinstance(prop_schema, dict) and prop_schema.get("readOnly") is True)
    }
    required_names = schema.get("required", [])
    required = [
        name for name in required_names if name in request_properties
    ] if isinstance(required_names, list) else []
    if len(required) > count:
        return None
    if additional is False and count > len(request_properties):
        return None

    value: dict = {}
    candidates = list(required)
    candidates.extend(name for name in request_properties if name not in required)
    for name in candidates:
        if len(value) >= count:
            break
        property_schema = request_properties.get(name)
        try:
            value[name] = find_schema_example(property_schema if isinstance(property_schema, dict) else {})
        except NoSchemaExample:
            return None

    extra_schema = additional if isinstance(additional, dict) else {}
    suffix = 1
    while len(value) < count:
        name = f"__extra_{suffix}"
        suffix += 1
        if name in value or name in properties:
            continue
        try:
            value[name] = find_schema_example(extra_schema)
        except NoSchemaExample:
            return None

    validation_schema = deepcopy(schema)
    if ignore_keyword:
        validation_schema.pop(ignore_keyword, None)
    _remove_read_only_properties(validation_schema)
    try:
        if not Draft202012Validator(validation_schema).is_valid(value):
            return None
    except SchemaError:
        return None
    return value


def _remove_read_only_properties(schema: dict) -> None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        read_only = {
            name for name, prop_schema in properties.items()
            if isinstance(prop_schema, dict) and prop_schema.get("readOnly") is True
        }
        for name in read_only:
            properties.pop(name, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [name for name in required if name not in read_only]
        for prop_schema in properties.values():
            if isinstance(prop_schema, dict):
                _remove_read_only_properties(prop_schema)
    items = schema.get("items")
    if isinstance(items, dict):
        _remove_read_only_properties(items)
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        _remove_read_only_properties(additional)
