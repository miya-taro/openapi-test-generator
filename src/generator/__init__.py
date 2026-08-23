"""ParamSpec / BodyFieldSpec / AuthSpec から TestCase を生成するメインロジック。"""
from __future__ import annotations

from .rules.common import generate_common_cases
from .rules.integer import generate_integer_cases
from .rules.string import generate_string_cases
from .rules.array import generate_array_cases
from .rules.object import generate_object_cases
from .rules.auth import generate_auth_cases


def _derive_response_body(info: dict | None) -> str:
    if not info:
        return ""
    content_types = info.get("contentTypes", [])
    if len(content_types) == 0:
        return "レスポンスボディなし"
    if "application/json" in content_types:
        return "OpenAPI定義のJSON schemaに従うこと"
    if len(content_types) == 1:
        return f"{content_types[0]} に従うレスポンスを返すこと"
    return "OpenAPIレスポンス定義を確認すること"


def _derive_response_header(info: dict | None) -> str:
    if not info:
        return ""
    content_types = info.get("contentTypes", [])
    headers_def = info.get("headers", {})
    lines: list[str] = []
    if len(content_types) == 1:
        lines.append(f"Content-Type: {content_types[0]}")
    elif len(content_types) > 1:
        lines.append("Content-Type: （複数あり・要確認）")
    for header_name, header_def in headers_def.items():
        concrete = _concrete_header_value(header_def)
        if concrete is not None:
            lines.append(f"{header_name}: {concrete}")
        else:
            lines.append(f"{header_name}: （存在確認のみ）")
    return "\n".join(lines)


def _concrete_header_value(header_def: dict | None) -> str | None:
    """OpenAPIのheaderオブジェクトから、具体的に一致検証できる値を取り出せる場合は返す。
    example/enum(1件)/defaultのいずれかがあれば使う。判断できない場合は None
    （呼び出し側は「存在確認のみ」の期待値として扱う）。"""
    if not header_def:
        return None
    if "example" in header_def:
        return str(header_def["example"])
    schema = header_def.get("schema") or {}
    if "example" in schema:
        return str(schema["example"])
    enum = schema.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return str(enum[0])
    if "default" in schema:
        return str(schema["default"])
    return None


# 現在の生成スコープ: Validation Keyword 単位のフィールド個別テスト（Layer 1）のみ。
# 以下は Layer 1 標準では扱わない:
#   - string フィールドへの型不正（実装依存で期待ステータスが安定しないため）
#   - Content-Type 不正 / integer への float / non-nullable への null（実装依存）
#   - 最小有効リクエスト（Layer 2 寄り）→ --generate-minimal-request として後付け予定（GenerateOptions 参照）
def generate_test_cases(
    param_specs: list[dict],
    body_specs: list[dict],
    opts: dict,
    auth_specs: list[dict] | None = None,
) -> list[dict]:
    auth_specs = auth_specs or []
    results: list[dict] = []

    for spec in param_specs:
        partials = _generate_from_schema(
            spec["schema"], spec["required"], spec["in"], spec["name"], opts, spec["successStatus"]
        )
        for partial in partials:
            responses_info = spec["responsesInfo"].get(partial["expectedStatus"])
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": spec["in"],
                "paramName": spec["name"],
                "verdict": "",
                **partial,
                "expectedResponseBody": _derive_response_body(responses_info),
                "expectedResponseHeader": _derive_response_header(responses_info),
                "expectedResponseTime": "3秒以内",
            })

    for spec in body_specs:
        is_root_body = spec["fieldPath"] == "__body__"
        param_in = "body"
        param_name = "requestBody" if is_root_body else spec["fieldPath"]

        partials = _generate_from_schema(
            spec["schema"], spec["required"], param_in, param_name, opts, spec["successStatus"], is_root_body
        )
        for partial in partials:
            responses_info = spec["responsesInfo"].get(partial["expectedStatus"])
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": param_in,
                "paramName": param_name,
                "verdict": "",
                **partial,
                "expectedResponseBody": _derive_response_body(responses_info),
                "expectedResponseHeader": _derive_response_header(responses_info),
                "expectedResponseTime": "3秒以内",
            })

    for spec in auth_specs:
        if not opts["includeAbnormal"]:
            continue
        partials = generate_auth_cases(spec)
        for partial in partials:
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": "header",
                "paramName": spec["headerName"],
                "verdict": "",
                **partial,
                "expectedResponseBody": "",
                "expectedResponseHeader": "",
                "expectedResponseTime": "3秒以内",
            })

    return results


def _generate_from_schema(
    schema: dict,
    required: bool,
    param_in: str,
    param_name: str,
    opts: dict,
    success_status: str,
    is_root_body: bool = False,
) -> list[dict]:
    cases: list[dict] = []
    ctx = {"paramIn": param_in, "paramName": param_name, "opts": opts, "successStatus": success_status}

    # 共通ルール（required, type）
    cases.extend(generate_common_cases(schema, required, ctx))

    type_ = schema.get("type")
    type_ = type_[0] if isinstance(type_, list) else type_

    if type_ in ("integer", "number"):
        cases.extend(generate_integer_cases(schema, ctx))
    elif type_ == "string":
        cases.extend(generate_string_cases(schema, ctx))
    elif type_ == "array":
        cases.extend(generate_array_cases(schema, ctx))
    elif type_ == "object":
        obj_ctx = {**ctx, "isRootBody": is_root_body}
        cases.extend(generate_object_cases(schema, obj_ctx))
    else:
        # type 不明の場合でも format/enum がある string 系を試みる
        if (
            schema.get("enum")
            or schema.get("format")
            or schema.get("maxLength") is not None
            or schema.get("minLength") is not None
            or schema.get("pattern")
        ):
            cases.extend(generate_string_cases(schema, ctx))

    return cases
