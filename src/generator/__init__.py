"""ParamSpec / BodyFieldSpec / AuthSpec から TestCase を生成するメインロジック。"""
from __future__ import annotations
import json
from jsonschema import Draft202012Validator, FormatChecker
from src.schema_contract import CONTRACT, validation_schema

from src.comparison_rules import KEY as COMPARISON_KEY, OPERATORS

from .rules.common import generate_common_cases, generate_one_of_variant_cases
from .rules.integer import generate_integer_cases
from .rules.string import generate_string_cases
from .rules.array import generate_array_cases
from .rules.boolean import generate_boolean_cases
from .rules.object import generate_object_cases
from .rules.auth import generate_auth_cases
from .rules.file import generate_file_cases


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
        if not isinstance(header_def, dict) or not header_def.get("required", False):
            continue
        concrete = _concrete_header_value(header_def)
        if concrete is not None:
            lines.append(f"{header_name}: {concrete}")
        else:
            lines.append(f"{header_name}: （存在確認のみ）")
    return "\n".join(lines)


def _derive_expected_response_body(expected_status: str, info: dict | None) -> str:
    if expected_status == "2xx":
        return "実測した成功statusに対応するOpenAPIレスポンスschemaに従うこと"
    return _derive_response_body(info)


def _derive_expected_response_header(expected_status: str, info: dict | None) -> str:
    if expected_status == "2xx":
        return "実測した成功statusに対応するOpenAPIレスポンスheaderを検証すること"
    return _derive_response_header(info)


def _response_info_for_status(expected_status: str, responses_info: dict) -> dict | None:
    if expected_status in responses_info:
        return responses_info[expected_status]
    if expected_status != "4xx":
        return None

    error_infos = [
        info for status, info in responses_info.items()
        if status.isdigit() and 400 <= int(status) < 500
    ]
    if not error_infos:
        return None

    common_types = set(error_infos[0].get("contentTypes", []))
    for info in error_infos[1:]:
        common_types.intersection_update(info.get("contentTypes", []))
    common_headers = dict(error_infos[0].get("headers", {}))
    for info in error_infos[1:]:
        common_headers = {
            name: definition for name, definition in common_headers.items()
            if name in info.get("headers", {}) and info["headers"][name] == definition
        }
    return {"contentTypes": sorted(common_types), "headers": common_headers}


def _concrete_header_value(header_def: dict | None) -> str | None:
    """OpenAPIのresponse headerから、契約として固定された値を取り出す。

    example/defaultは実際の応答値を制約するものではないため一致検証に使わない。
    constまたは単一値enumだけを完全一致し、それ以外はschema検証または存在確認に委ねる。
    """
    if not header_def:
        return None
    schema = header_def.get("schema") or {}
    if "const" in schema:
        return str(schema["const"])
    enum = schema.get("enum")
    if isinstance(enum, list) and len(enum) == 1:
        return str(enum[0])
    return None


# Layer 1 の schema-negative ケースは特定の 400 ではなく 4xx を期待する。
# OpenAPI は不正な値ごとに 400 / 422 等を対応付けないため、具体的な業務エラーコードは
# DBシナリオ等で人が定義し、契約ケースでは「クライアントエラーとして拒否される」ことを確認する。
def generate_test_cases(
    param_specs: list[dict],
    body_specs: list[dict],
    opts: dict,
    auth_specs: list[dict] | None = None,
) -> list[dict]:
    auth_specs = auth_specs or []
    results: list[dict] = []

    for spec in param_specs:
        if spec.get("operationBaseline"):
            if not opts["includeNormal"]:
                continue
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": "operation",
                "paramName": "__valid_request__",
                "verdict": "",
                "summary": f"{spec['operationId']} 最小有効リクエスト（正常）",
                "keyword": "request",
                "perspective": "正常系_最小有効リクエスト",
                "inputValue": "（最小有効リクエスト）",
                "expectedStatus": spec["successStatus"],
                "expectedResult": "必須の入力を満たしたリクエストが正常に処理され、定義済み成功レスポンスのいずれかが返ること",
                "notes": "OpenAPIに定義された必須path/query/header/cookie parameterと必須requestBodyを送信",
                "expectedResponseBody": _derive_expected_response_body(spec["successStatus"], None),
                "expectedResponseHeader": _derive_expected_response_header(spec["successStatus"], None),
                "expectedResponseTime": "3秒以内",
            })
            continue

        if spec.get("unsupportedContentType"):
            if not opts["includeAbnormal"]:
                continue
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": "header",
                "paramName": "Content-Type",
                "verdict": "",
                "summary": f"Content-Type 不正値（{spec['unsupportedContentType']}）",
                "keyword": "contentType",
                "perspective": "異常系_Content-Type不正",
                "inputValue": spec["unsupportedContentType"],
                "expectedStatus": "415",
                "expectedResult": "Unsupported Media Type が返ること",
                "notes": "OpenAPI に 415 応答が定義されているため、本文を保ったまま未対応メディアタイプを送信",
                "expectedResponseBody": _derive_response_body(spec["responsesInfo"].get("415")),
                "expectedResponseHeader": _derive_response_header(spec["responsesInfo"].get("415")),
                "expectedResponseTime": "3秒以内",
            })
            continue

        partials = _generate_from_schema(
            spec["schema"], spec["required"], spec["in"], spec["name"], opts, spec["successStatus"]
        )
        for partial in partials:
            expected_status = partial["expectedStatus"]
            responses_info = _response_info_for_status(expected_status, spec["responsesInfo"])
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": spec["in"],
                "paramName": spec["name"],
                "verdict": "",
                **partial,
                "expectedResponseBody": _derive_expected_response_body(expected_status, responses_info),
                "expectedResponseHeader": _derive_expected_response_header(expected_status, responses_info),
                "expectedResponseTime": "3秒以内",
            })

    for spec in body_specs:
        is_root_body = spec["fieldPath"] == "__body__"
        param_in = "body"
        field_path = spec["fieldPath"]
        if is_root_body:
            param_name = "requestBody"
        elif field_path.startswith("[]"):
            param_name = f"requestBody{field_path}"
        else:
            param_name = field_path

        partials = _generate_from_schema(
            spec["schema"], spec["required"], param_in, param_name, opts, spec["successStatus"], is_root_body,
            skip_presence=bool(spec.get("schemaOnly")),
        )
        for partial in partials:
            expected_status = partial["expectedStatus"]
            responses_info = _response_info_for_status(expected_status, spec["responsesInfo"])
            results.append({
                "operationId": spec["operationId"],
                "path": spec["path"],
                "method": spec["method"],
                "in": param_in,
                "paramName": param_name,
                "verdict": "",
                **partial,
                "expectedResponseBody": _derive_expected_response_body(expected_status, responses_info),
                "expectedResponseHeader": _derive_expected_response_header(expected_status, responses_info),
                "expectedResponseTime": "3秒以内",
            })

        if is_root_body and (opts["includeNormal"] or opts["includeAbnormal"]):
            rules = spec["schema"].get("x-otg-presence-rules") or []
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict) or rule.get("kind") not in {"atLeastOne", "together"}:
                    continue
                fields = rule.get("fields") or []
                if len(fields) != 2 or not all(isinstance(name, str) for name in fields):
                    continue
                variants = (
                    [("neither", False), ("first", True), ("second", True), ("both", True)]
                    if rule["kind"] == "atLeastOne" else
                    [("first", False), ("second", False), ("neither", True), ("both", True)]
                )
                for variant, valid in variants:
                    if valid and spec["successStatus"] is None:
                        continue
                    if not opts["includeNormal" if valid else "includeAbnormal"]:
                        continue
                    expected_status = spec["successStatus"] if valid else "4xx"
                    responses_info = _response_info_for_status(expected_status, spec["responsesInfo"])
                    results.append({
                        "operationId": spec["operationId"], "path": spec["path"], "method": spec["method"],
                        "in": "body", "paramName": "requestBody", "verdict": "",
                        "summary": f"{fields[0]}・{fields[1]} 条件付き必須（{variant}）",
                        "keyword": "conditionalRequired", "perspective": "正常系_条件付き必須" if valid else "異常系_条件付き必須",
                        "inputValue": f"__PRESENCE_RULE__{index}:{variant}",
                        "expectedStatus": expected_status,
                        "expectedResult": "条件付き必須の指定に従うこと",
                        "notes": "UIで指定した項目間の必須条件",
                        "expectedResponseBody": _derive_expected_response_body(expected_status, responses_info),
                        "expectedResponseHeader": _derive_expected_response_header(expected_status, responses_info),
                        "expectedResponseTime": "3秒以内",
                    })

        if is_root_body:
            for index, rule in enumerate(spec["schema"].get(COMPARISON_KEY, [])):
                for variant, ordering in (("less", -1), ("equal", 0), ("greater", 1)):
                    valid = OPERATORS[rule["operator"]](ordering, 0)
                    if valid and spec["successStatus"] is None:
                        continue
                    if not opts["includeNormal" if valid else "includeAbnormal"]:
                        continue
                    expected_status = spec["successStatus"] if valid else "4xx"
                    responses_info = _response_info_for_status(expected_status, spec["responsesInfo"])
                    left, right = rule["fields"]
                    results.append({
                        "operationId": spec["operationId"], "path": spec["path"], "method": spec["method"],
                        "in": "body", "paramName": "requestBody", "verdict": "",
                        "summary": f"{left} {rule['operator']} {right}（{variant}）",
                        "keyword": "fieldComparison", "perspective": "正常系_項目間比較" if valid else "異常系_項目間比較",
                        "inputValue": f"__COMPARISON_RULE__{index}:{variant}",
                        "expectedStatus": expected_status,
                        "expectedResult": "設定した項目間の大小条件に従うこと",
                        "notes": "両項目の指定時に比較。小さい値・等しい値・大きい値を確認",
                        "expectedResponseBody": _derive_expected_response_body(expected_status, responses_info),
                        "expectedResponseHeader": _derive_expected_response_header(expected_status, responses_info),
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
    success_status: str | None,
    is_root_body: bool = False,
    skip_presence: bool = False,
) -> list[dict]:
    cases: list[dict] = []
    if success_status is None:
        opts = {**opts, "includeNormal": False}
    ctx = {
        "paramIn": param_in, "paramName": param_name, "opts": opts,
        "successStatus": success_status, "isRootBody": is_root_body,
        "skipPresence": skip_presence,
    }

    # 共通ルール（required, type）
    cases.extend(generate_common_cases(schema, required, ctx))

    # --one-of-full-coverage 指定時のみ: oneOf/anyOf の代表バリアント以外にも正常系ケースを追加
    cases.extend(generate_one_of_variant_cases(schema, ctx))

    type_ = schema.get("type")
    if isinstance(type_, list):
        # OAS 3.1 の type 配列は順不同（例: ["null", "string"]）。先頭要素だけを見て
        # 振り分け先を決めると、"null" が先に来る書き方（nullable な型で一般的）の場合、
        # 実際の型（string/integer/array/object）に対応するルールが一切呼ばれず、
        # 型別の境界値・異常系ケースが丸ごと生成されない（このファイル末尾の
        # フォールバック分岐は format/enum/maxLength/minLength/pattern しか救えないため、
        # 特に array/object/integer では何も救われない）。"null" を除いた最初の型を使う。
        non_null = [t for t in type_ if t != "null"]
        type_ = non_null[0] if non_null else None

    if schema.get("format") == "binary":
        # multipart/form-data のファイルアップロードフィールド。type は "string" だが
        # minLength/maxLength/pattern/format 等の文字列系ルールは意味を持たないため、
        # 型別ルール（generate_string_cases 等）には渡さず専用ルールで扱う。
        cases.extend(generate_file_cases(ctx))
    elif type_ in ("integer", "number"):
        cases.extend(generate_integer_cases(schema, ctx))
    elif type_ == "string":
        cases.extend(generate_string_cases(schema, ctx))
    elif type_ == "boolean":
        cases.extend(generate_boolean_cases(schema, ctx))
        if schema.get("enum"):
            cases.extend(generate_string_cases(schema, ctx))
    elif type_ == "array":
        cases.extend(generate_array_cases(schema, ctx))
    elif type_ == "object":
        cases.extend(generate_object_cases(schema, ctx))
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

    if CONTRACT in schema:
        validator = Draft202012Validator(validation_schema(schema), format_checker=FormatChecker())
        filtered = []
        for case in cases:
            raw = case["inputValue"]
            if raw.startswith(("（", "__")) and raw != "（空文字）":
                filtered.append(case)
                continue
            try:
                value = "" if raw == "（空文字）" else json.loads(raw)
            except (ValueError, TypeError):
                value = raw
            if validator.is_valid(value) == case["perspective"].startswith("正常"):
                filtered.append(case)
        return filtered
    return cases
