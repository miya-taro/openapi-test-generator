from __future__ import annotations
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

MAX_ERRORS = 10


def resolve_response_schema(operation_id: str, path: str, method: str, status: str, openapi: dict) -> dict | None:
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

    response = (op.get("responses") or {}).get(str(status))
    if not response:
        return None

    content = response.get("content") or {}
    json_content = content.get("application/json")
    if not json_content:
        return None

    schema = json_content.get("schema")
    if not isinstance(schema, dict) or not schema:
        return None
    return _strip_write_only(schema)


def _strip_write_only(schema: dict) -> dict:
    """レスポンス検証用のスキーマから writeOnly なプロパティを取り除く。

    writeOnly（例: password）はリクエスト専用のフィールドで、サーバーがレスポンスに
    含めることは仕様上ないため、含まれていないことを理由に誤ってNG判定してしまうのを防ぐ。
    元のスキーマ（openapiドキュメント内で共有されている可能性がある）は変更せず、
    新しい辞書を組み立てて返す。
    """
    result = dict(schema)

    properties = result.get("properties")
    if isinstance(properties, dict):
        new_props = {}
        for name, prop_schema in properties.items():
            if isinstance(prop_schema, dict) and prop_schema.get("writeOnly"):
                continue
            new_props[name] = _strip_write_only(prop_schema) if isinstance(prop_schema, dict) else prop_schema
        result["properties"] = new_props
        required = result.get("required")
        if isinstance(required, list):
            result["required"] = [r for r in required if r in new_props]

    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = _strip_write_only(items)

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

    try:
        validator = Draft202012Validator(schema)
    except SchemaError as e:
        return [f"スキーマが不正です（検証をスキップ）: {e}"]

    errors = sorted(validator.iter_errors(parsed), key=lambda e: list(map(str, e.path)))
    if not errors:
        return []

    messages = []
    for e in errors[:MAX_ERRORS]:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        messages.append(f"{loc}: {e.message}")
    if len(errors) > MAX_ERRORS:
        messages.append(f"...他 {len(errors) - MAX_ERRORS} 件のエラー")
    return messages
