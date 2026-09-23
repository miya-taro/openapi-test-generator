from __future__ import annotations
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sensitive_data import WRITE_ONLY_SCHEMA_MARKER

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

    responses = op.get("responses") or {}
    # 個別のステータスコードが明示されていなければ、OpenAPIの "default"
    # レスポンス（列挙されていない全ステータスの受け皿）にフォールバックする。
    # これを見ないと、"default" にしかスキーマが無いエンドポイントは
    # Level 4（レスポンスボディのスキーマ適合）検証が常にスキップされてしまう。
    response = responses.get(str(status)) or responses.get("default")
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
        validator = Draft202012Validator(schema)
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
