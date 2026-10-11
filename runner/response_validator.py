from __future__ import annotations
import json
import math
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from sensitive_data import WRITE_ONLY_SCHEMA_MARKER

MAX_ERRORS = 10


def resolve_response_schema(
    operation_id: str,
    path: str,
    method: str,
    status: str,
    openapi: dict,
    content_type: str | None = None,
) -> dict | None:
    """openapi（src.parser.parse_openapi 済みで $ref/allOf/oneOf/anyOf 解決済みの前提）から
    該当 operation の該当ステータスのレスポンス JSON Schema を取得する。
    定義がない場合（ボディなしのレスポンス等）は None を返す。
    """
    paths = openapi.get("paths", {})
    path_item = paths.get(path)
    if path_item is None:
        path_item = _find_path_by_operation_id(paths, operation_id)
    if path_item is None:
        return None

    op = path_item.get(method.lower())
    if op is None:
        return None

    responses = op.get("responses") or {}
    # 個別のステータスコードが明示されていなければ、OpenAPIの "default"
    # レスポンス（列挙されていない全ステータスの受け皿）にフォールバックする。
    # これを見ないと、"default" にしかスキーマが無いエンドポイントは
    # Level 4（レスポンスボディのスキーマ適合）検証が常にスキップされてしまう。
    response = responses.get(str(status))
    if response is None:
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            status_code = None
        if status_code is not None:
            response = next(
                (value for code, value in responses.items()
                 if str(code).upper() == f"{status_code // 100}XX"),
                None,
            )
    if response is None:
        response = responses.get("default")
    if not response:
        return None

    content = response.get("content") or {}
    selected_content = None
    if content_type:
        selected_content = next(
            (value for media_type, value in content.items() if _media_type_matches(content_type, media_type)),
            None,
        )
    else:
        selected_content = content.get("application/json")
        if selected_content is None:
            json_media_types = [
                value for media_type, value in content.items()
                if str(media_type).lower().endswith("+json")
            ]
            if len(json_media_types) == 1:
                selected_content = json_media_types[0]
    if not selected_content:
        return None

    schema = selected_content.get("schema")
    if not isinstance(schema, dict) or not schema:
        return None
    return _strip_write_only(schema)


def _media_type_matches(actual: str, expected: str) -> bool:
    actual_media = actual.split(";", 1)[0].strip().lower()
    expected_media = expected.split(";", 1)[0].strip().lower()
    if "*" not in expected_media:
        return actual_media == expected_media
    pattern = "^" + re.escape(expected_media).replace(r"\*", ".*") + "$"
    return re.fullmatch(pattern, actual_media) is not None


def _strip_write_only(schema: dict) -> dict:
    """writeOnly なプロパティを任意かつ禁止のレスポンス項目に変換する。

    writeOnly（例: password）はリクエスト専用のフィールドで、サーバーがレスポンスに
    含めることは仕様上ない。required からは外し、実際に現れた場合は値を含めず違反として
    報告する。
    元のスキーマ（openapiドキュメント内で共有されている可能性がある）は変更せず、
    新しい辞書を組み立てて返す。
    """
    result = dict(schema)

    properties = result.get("properties")
    if isinstance(properties, dict):
        new_props = {}
        write_only_names = set()
        for name, prop_schema in properties.items():
            if isinstance(prop_schema, dict) and prop_schema.get("writeOnly"):
                new_props[name] = {"not": {}, WRITE_ONLY_SCHEMA_MARKER: True}
                write_only_names.add(name)
                continue
            new_props[name] = _strip_write_only(prop_schema) if isinstance(prop_schema, dict) else prop_schema
        result["properties"] = new_props
        required = result.get("required")
        if isinstance(required, list):
            result["required"] = [r for r in required if r in new_props and r not in write_only_names]

    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = _strip_write_only(items)

    # additionalProperties がスキーマ（動的キーの値の形を定義）の場合も再帰する。
    # bool（true/false）はスキーマではないのでそのまま。ここを見落とすと、動的キーの値側に
    # ネストした writeOnly な必須プロパティが required に残ったままになり、
    # 実際には正しく省略されているレスポンスを誤ってNG判定してしまう。
    additional_props = result.get("additionalProperties")
    if isinstance(additional_props, dict):
        result["additionalProperties"] = _strip_write_only(additional_props)

    variants = result.get("_oneOfVariants")
    if isinstance(variants, list):
        result["_oneOfVariants"] = [_strip_write_only(v) if isinstance(v, dict) else v for v in variants]

    return result


def _find_path_by_operation_id(paths: dict, operation_id: str) -> dict | None:
    for path_item in paths.values():
        for method_item in path_item.values():
            if isinstance(method_item, dict) and method_item.get("operationId") == operation_id:
                return path_item
    return None


def validate_body(actual_body: str, schema: dict | None) -> list[str]:
    """actual_body（JSON文字列）が schema に適合するか検証する。

    違反があれば人間可読なメッセージのリストを返す（適合していれば空リスト）。
    schema が None（該当ステータスにレスポンスボディ定義がない）の場合は検証対象外として空リストを返す。
    """
    if not schema:
        return []

    if not actual_body or not actual_body.strip():
        return ["レスポンスボディが空です（スキーマ定義があるため空は不正）"]

    try:
        parsed: Any = json.loads(actual_body)
    except json.JSONDecodeError as e:
        return [f"レスポンスボディがJSONとして解析できません: {e}"]

    # レスポンススキーマのルート直下が oneOf/anyOf の場合、parser.py（_reduce_one_of_any_of）は
    # 代表バリアント（1番目）の形にスキーマを平坦化している。そのため通常の Draft202012Validator
    # では、サーバーが正当に2番目以降のバリアント形状でレスポンスを返した場合でも
    # スキーマ不適合として誤NG判定してしまう。schema["_oneOfVariants"]（全バリアントの
    # 正規化済みスキーマ）が残っていれば、いずれか1つに適合すれば OK とする。
    variants = schema.get("_oneOfVariants")
    if variants:
        return _validate_against_any_variant(parsed, variants)

    return _validate_against_schema(parsed, schema)


def validate_header_value(actual_value: str, header_definition: dict) -> list[str]:
    """Validate a serialized response header against its OpenAPI Header Object schema.

    HTTP header fields arrive as strings. The common OpenAPI `simple` serialization is decoded
    for integer, number, boolean, array, and object schemas before applying JSON Schema rules.
    Error details identify the failed constraint without echoing the header value.
    """
    schema = header_definition.get("schema")
    if not isinstance(schema, dict) or not schema:
        return []
    try:
        value = _parse_simple_header_value(actual_value, schema, header_definition)
    except ValueError:
        return ["ヘッダ値をOpenAPIの型として読み取れません"]
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    except SchemaError:
        return ["OpenAPIヘッダschemaが不正です"]
    errors = sorted(validator.iter_errors(value), key=lambda error: list(map(str, error.path)))
    return [
        f"schema制約 {error.validator!s} に不適合"
        for error in errors[:MAX_ERRORS]
    ]


def _parse_simple_header_value(raw: str, schema: dict, header_definition: dict) -> Any:
    type_ = _header_schema_type(schema)
    if type_ == "integer":
        if not raw or raw.strip() != raw or not raw.lstrip("+-").isdigit():
            raise ValueError("invalid integer")
        return int(raw)
    if type_ == "number":
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError("invalid number") from error
        if not math.isfinite(value):
            raise ValueError("invalid number")
        return value
    if type_ == "boolean":
        lowered = raw.lower()
        if lowered not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return lowered == "true"
    if type_ == "array":
        item_schema = schema.get("items") or {}
        return [
            _parse_simple_header_scalar(part.strip(), item_schema)
            for part in raw.split(",")
        ]
    if type_ == "object":
        explode = header_definition.get("explode", False)
        parts = [part.strip() for part in raw.split(",")]
        if explode:
            result = {}
            for part in parts:
                key, separator, value = part.partition("=")
                if not separator or not key:
                    raise ValueError("invalid object")
                result[key] = value
            return _coerce_header_object(result, schema)
        if len(parts) % 2:
            raise ValueError("invalid object")
        return _coerce_header_object(dict(zip(parts[::2], parts[1::2], strict=True)), schema)
    return raw


def _parse_simple_header_scalar(raw: str, schema: dict) -> Any:
    type_ = _header_schema_type(schema)
    if type_ == "integer":
        if not raw or raw.strip() != raw or not raw.lstrip("+-").isdigit():
            raise ValueError("invalid integer")
        return int(raw)
    if type_ == "number":
        try:
            value = float(raw)
        except ValueError as error:
            raise ValueError("invalid number") from error
        if not math.isfinite(value):
            raise ValueError("invalid number")
        return value
    if type_ == "boolean":
        lowered = raw.lower()
        if lowered not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return lowered == "true"
    return raw


def _coerce_header_object(value: dict[str, str], schema: dict) -> dict[str, Any]:
    properties = schema.get("properties") or {}
    additional = schema.get("additionalProperties")
    result: dict[str, Any] = {}
    for name, raw in value.items():
        property_schema = properties.get(name)
        if not isinstance(property_schema, dict) and isinstance(additional, dict):
            property_schema = additional
        result[name] = _parse_simple_header_scalar(raw, property_schema or {})
    return result


def _header_schema_type(schema: dict) -> str | None:
    type_ = schema.get("type")
    if isinstance(type_, list):
        return "string" if "string" in type_ else next((item for item in type_ if item != "null"), None)
    if isinstance(type_, str):
        return type_
    values = schema.get("enum")
    if not isinstance(values, list):
        values = [schema["const"]] if "const" in schema else []
    if values and all(isinstance(value, bool) for value in values):
        return "boolean"
    if values and all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    if values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return "number"
    if values and all(isinstance(value, str) for value in values):
        return "string"
    return None


def _validate_against_any_variant(parsed: Any, variants: list[dict]) -> list[str]:
    first_errors: list[str] | None = None
    write_only_errors: list[str] = []
    for variant in variants:
        errors = _validate_against_schema(parsed, variant)
        if not errors:
            return []
        if first_errors is None:
            first_errors = errors
        write_only_errors.extend(
            error for error in errors if "writeOnlyフィールドがレスポンスに含まれています" in error
        )

    if write_only_errors:
        return list(dict.fromkeys(write_only_errors))

    messages = [
        f"oneOf/anyOf の {len(variants)} 件のバリアントいずれにも適合しませんでした"
        "（1番目のバリアントに対するエラーを表示）:"
    ]
    messages.extend(first_errors or [])
    return messages


def _validate_against_schema(parsed: Any, schema: dict) -> list[str]:
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    except SchemaError as e:
        return [f"スキーマが不正です（検証をスキップ）: {e}"]

    errors = sorted(validator.iter_errors(parsed), key=lambda e: list(map(str, e.path)))
    if not errors:
        return []

    messages = []
    for e in errors[:MAX_ERRORS]:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        if _contains_write_only_violation(e):
            messages.append(f"{loc}: writeOnlyフィールドがレスポンスに含まれています")
        else:
            messages.append(f"{loc}: {e.message}")
    if len(errors) > MAX_ERRORS:
        messages.append(f"...他 {len(errors) - MAX_ERRORS} 件のエラー")
    return messages


def _contains_write_only_violation(error: Any) -> bool:
    """oneOf/anyOf などの子エラーに含まれる writeOnly 違反を再帰的に見つける。"""
    if (
        error.validator == "not"
        and isinstance(error.schema, dict)
        and error.schema.get(WRITE_ONLY_SCHEMA_MARKER) is True
    ):
        return True
    return any(_contains_write_only_violation(child) for child in error.context)
