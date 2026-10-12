"""OpenAPI ドキュメントから ParamSpec / BodyFieldSpec / AuthSpec を抽出する。"""
from __future__ import annotations
import re

from . import logger as log
from .schema_example import NoSchemaExample, find_schema_example

STANDARD_HEADERS = {
    "authorization",
    "content-type",
    "accept",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "connection",
    "host",
    "user-agent",
}

_METHODS_FOR_AUTH = ("get", "post", "put", "patch", "delete")
_METHODS_ALL = ("get", "post", "put", "patch", "delete", "options", "head")


def extract_auth_specs(api: dict) -> list[dict]:
    specs: list[dict] = []
    global_security = api.get("security")
    security_schemes = (api.get("components") or {}).get("securitySchemes", {}) or {}
    paths = api.get("paths") or {}

    for path, path_item in paths.items():
        if not path_item:
            continue

        for method in _METHODS_FOR_AUTH:
            operation = path_item.get(method)
            if not operation:
                continue

            op_security = operation["security"] if "security" in operation else global_security
            if not op_security:
                continue
            # Security Requirement Object 配列は OR、各オブジェクト内のキーは AND。
            # 空オブジェクトが一つでもあれば認証なしの選択肢があるため、401/403期待の
            # 認証拒否ケースは作らない（公開操作を誤ってNGにしない）。
            if any(isinstance(requirement, dict) and not requirement for requirement in op_security):
                continue

            credentials: list[dict] = []
            seen_credentials: set[tuple[str, str]] = set()
            for requirement in op_security:
                if not isinstance(requirement, dict):
                    continue
                for scheme_name in requirement:
                    scheme = security_schemes.get(scheme_name, {}) or {}
                    scheme_type = "other"
                    location = "header"
                    name = "Authorization"

                    if scheme.get("type") == "http" and scheme.get("scheme", "").lower() == "bearer":
                        scheme_type = "bearer"
                    elif scheme.get("type") == "http" and scheme.get("scheme", "").lower() == "basic":
                        scheme_type = "basic"
                    elif scheme.get("type") == "apiKey":
                        scheme_type = "apiKey"
                        location = scheme.get("in", "header")
                        if location not in {"header", "query", "cookie"}:
                            location = "header"
                        name = scheme.get("name") or "X-Api-Key"

                    identity = (location, name.lower() if location == "header" else name)
                    if identity in seen_credentials:
                        continue
                    seen_credentials.add(identity)
                    credentials.append({
                        "schemeName": str(scheme_name),
                        "schemeType": scheme_type,
                        "in": location,
                        "name": name,
                    })

            if not credentials:
                continue

            first_credential = credentials[0]

            operation_id = _resolve_operation_id(operation, method, path)
            success_status = _resolve_success_status(operation.get("responses"))
            responses_info = _build_responses_info(operation.get("responses"))

            specs.append({
                "operationId": operation_id,
                "path": path,
                "method": method.upper(),
                "schemeType": first_credential["schemeType"],
                "headerName": first_credential["name"],
                "securitySchemes": credentials,
                "successStatus": success_status,
                "responsesInfo": responses_info,
            })

    return specs


def extract_specs(api: dict) -> tuple[list[dict], list[dict]]:
    param_specs: list[dict] = []
    body_specs: list[dict] = []
    paths = api.get("paths") or {}

    for path, path_item in paths.items():
        if not path_item:
            continue

        for method in _METHODS_ALL:
            operation = path_item.get(method)
            if not operation:
                continue

            operation_id = _resolve_operation_id(operation, method, path)
            success_status = _resolve_success_status(operation.get("responses"))
            responses_info = _build_responses_info(operation.get("responses"))

            parameters = _merge_parameters(
                path_item.get("parameters") or [],
                operation.get("parameters") or [],
            )
            baseline_supported = _required_parameters_have_examples(parameters)

            for param in parameters:
                name = param.get("name")
                param_in = param.get("in")
                if not name or not param_in:
                    continue

                if param_in == "header" and name.lower() in STANDARD_HEADERS:
                    log.debug({"name": name}, "標準ヘッダをスキップ")
                    continue

                schema = param.get("schema") or {}

                if schema.get("format") == "binary":
                    log.debug({"name": name}, "binary フィールドをスキップ")
                    continue

                param_specs.append({
                    "operationId": operation_id,
                    "path": path,
                    "method": method.upper(),
                    "in": param_in,
                    "name": name,
                    "required": True if param_in == "path" else bool(param.get("required", False)),
                    "schema": schema,
                    "successStatus": success_status,
                    "responsesInfo": responses_info,
                })

            request_body = operation.get("requestBody")
            if request_body:
                content = request_body.get("content") or {}
                json_content = content.get("application/json")
                multipart_content = content.get("multipart/form-data")

                if json_content:
                    content_type = "application/json"
                    picked_content = json_content
                elif multipart_content:
                    content_type = "multipart/form-data"
                    picked_content = multipart_content
                else:
                    log.debug(
                        {"operationId": operation_id},
                        "application/json / multipart/form-data 以外の requestBody をスキップ",
                    )
                    continue

                if any(str(code).upper() == "4XX" or (str(code).isdigit() and 400 <= int(code) < 500)
                       for code in (operation.get("responses") or {})):
                    supported_types = {str(value).lower() for value in content}
                    invalid_type = "application/x-api-tester-invalid"
                    while invalid_type in supported_types:
                        invalid_type += "-x"
                    param_specs.append({
                        "operationId": operation_id,
                        "path": path,
                        "method": method.upper(),
                        "in": "header",
                        "name": "Content-Type",
                        "required": True,
                        "schema": {},
                        "successStatus": "4xx",
                        "responsesInfo": responses_info,
                        "unsupportedContentType": invalid_type,
                    })

                body_schema = picked_content.get("schema")
                if body_schema:
                    fields = _flatten_body_schema(
                        body_schema, "", operation_id, path, method.upper(), success_status, responses_info,
                        content_type, request_body_required=bool(request_body.get("required", False)),
                    )
                    body_specs.extend(fields)
                    if request_body.get("required"):
                        baseline_supported = baseline_supported and _request_body_has_example(
                            body_schema, content_type,
                        )
                elif request_body.get("required"):
                    baseline_supported = False

            # Every operation gets one whole-request happy-path case. The runner uses this marker
            # to synthesize all required path/query/header/cookie parameters and the required body
            # together, so a valid response contract can be exercised even when no individual
            # property has a boundary keyword such as minLength or enum.
            if success_status is None:
                log.warn({"operationId": operation_id}, "成功レスポンスが未定義のため正常系を生成しません。期待statusはシナリオで指定してください")
            elif baseline_supported:
                param_specs.append({
                    "operationBaseline": True,
                    "operationId": operation_id,
                    "path": path,
                    "method": method.upper(),
                    "in": "operation",
                    "name": "__valid_request__",
                    "required": False,
                    "schema": {},
                    "successStatus": success_status,
                    "responsesInfo": responses_info,
                })
            else:
                log.warn(
                    {"operationId": operation_id},
                    "有効な最小リクエストを合成できないため、正常リクエスト共通ケースを省略",
                )

    return param_specs, body_specs


def _merge_parameters(path_params: list[dict], operation_params: list[dict]) -> list[dict]:
    """path 階層のパラメータに operation 階層のパラメータをマージする。

    OpenAPI の仕様上、同じ name/in の組み合わせは operation 階層側が
    path 階層側を上書きする（両方が有効になるわけではない）。
    """
    merged: dict[tuple[str | None, str | None], dict] = {}
    for param in (*path_params, *operation_params):
        key = (param.get("name"), param.get("in"))
        merged[key] = param
    return list(merged.values())


def _required_parameters_have_examples(parameters: list[dict]) -> bool:
    for parameter in parameters:
        if parameter.get("in") != "path" and not parameter.get("required"):
            continue
        if parameter.get("in") not in {"path", "query", "header", "cookie"} or not parameter.get("name"):
            return False
        schema = parameter.get("schema")
        if not isinstance(schema, dict):
            return False
        try:
            find_schema_example(schema)
        except NoSchemaExample:
            return False
    return True


def _request_body_has_example(schema: dict, content_type: str) -> bool:
    if content_type != "multipart/form-data":
        try:
            find_schema_example(schema)
            return True
        except NoSchemaExample:
            return False

    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        field_schema = properties.get(name)
        if not isinstance(field_schema, dict):
            return False
        if field_schema.get("format") == "binary":
            continue
        try:
            find_schema_example(field_schema)
        except NoSchemaExample:
            return False
    return True


def _resolve_success_status(responses: dict | None) -> str | None:
    if not responses:
        return "200"
    success_codes = [
        code for code in responses
        if re.fullmatch(r"2\d\d", str(code)) or str(code).upper() == "2XX"
    ]
    return "2xx" if success_codes else None


def _build_responses_info(responses: dict | None) -> dict:
    if not responses:
        return {}
    result: dict = {}
    for status, response in responses.items():
        if not response:
            continue
        content = response.get("content")
        headers = response.get("headers")
        result[status] = {
            "contentTypes": list(content.keys()) if content else [],
            "headerNames": list(headers.keys()) if headers else [],
            "headers": headers or {},
        }
    return result


def _resolve_operation_id(operation: dict, method: str, path: str) -> str:
    op_id = operation.get("operationId")
    if op_id:
        return op_id
    normalized = re.sub(r"\{([^}]+)\}", r"\1", path)
    normalized = normalized.replace("/", "_")
    normalized = re.sub(r"^_", "", normalized)
    return f"{method.upper()}_{normalized}"


def _has_type(schema: dict, type_name: str) -> bool:
    """schema["type"] が文字列（従来形式）でも配列（OAS 3.1、例: ["array", "null"]）
    でも type_name を含むかどうかを判定する。"""
    t = schema.get("type")
    if isinstance(t, list):
        return type_name in t
    return t == type_name


def _flatten_body_schema(
    schema: dict,
    parent_path: str,
    operation_id: str,
    path: str,
    method: str,
    success_status: str | None,
    responses_info: dict,
    content_type: str = "application/json",
    request_body_required: bool = False,
) -> list[dict]:
    results: list[dict] = []
    is_multipart = content_type == "multipart/form-data"
    is_root = parent_path == ""

    # A request body is itself a schema node, even when its root type is not object.
    # Keep its requiredness separate from the required properties inside an object.
    if is_root and not is_multipart:
        results.append({
            "operationId": operation_id,
            "path": path,
            "method": method,
            "fieldPath": "__body__",
            "required": request_body_required,
            "schema": schema,
            "successStatus": success_status,
            "responsesInfo": responses_info,
            "contentType": content_type,
        })

    if schema.get("type") == "object" or "properties" in schema:
        required_fields = set(schema.get("required") or [])
        properties = schema.get("properties") or {}

        for prop_name, prop_schema in properties.items():
            if not prop_schema:
                continue

            field_path = f"{parent_path}.{prop_name}" if parent_path else prop_name

            if prop_schema.get("format") == "binary" and not is_multipart:
                # application/json のボディにバイナリフィールドは現れない想定
                # （multipart/form-data のファイルアップロードフィールドとして本来送るべき値）。
                log.debug({"fieldPath": field_path}, "binary フィールドをスキップ")
                continue

            if prop_schema.get("readOnly"):
                # readOnly はサーバー側専用のフィールド（例: id, createdAt）で、
                # クライアントがリクエストに含めるものではないため、リクエストボディの
                # フィールド単位テスト対象からは除外する。
                log.debug({"fieldPath": field_path}, "readOnly フィールドをスキップ")
                continue

            results.append({
                "operationId": operation_id,
                "path": path,
                "method": method,
                "fieldPath": field_path,
                "required": prop_name in required_fields,
                "schema": prop_schema,
                "successStatus": success_status,
                "responsesInfo": responses_info,
                "contentType": content_type,
            })

            # ネストされたオブジェクトを再帰的に展開
            if prop_schema.get("type") == "object" or "properties" in prop_schema:
                results.extend(
                    _flatten_body_schema(
                        prop_schema, field_path, operation_id, path, method, success_status, responses_info,
                        content_type, request_body_required,
                    )
                )

            elif _has_type(prop_schema, "array"):
                results.extend(_flatten_body_schema(
                    prop_schema, field_path, operation_id, path, method, success_status, responses_info,
                    content_type, request_body_required,
                ))

    elif _has_type(schema, "array") and not is_multipart and schema.get("maxItems") != 0:
        # The array's own schema creates minItems/maxItems cases. Create item-level
        # specs too, so item type/constraints and nested object properties are covered.
        items_schema = schema.get("items")
        if isinstance(items_schema, dict):
            # Use the conventional `items[].field` spelling in generated specifications.
            # The request builder still accepts the older `items.[].field` form for cases
            # created by earlier generator versions.
            item_path = f"{parent_path}[]" if parent_path else "[]"
            results.append({
                "operationId": operation_id,
                "path": path,
                "method": method,
                "fieldPath": item_path,
                "required": False,
                "schema": items_schema,
                "successStatus": success_status,
                "responsesInfo": responses_info,
                "contentType": content_type,
                "schemaOnly": True,
            })
            results.extend(_flatten_body_schema(
                items_schema, item_path, operation_id, path, method, success_status, responses_info,
                content_type, request_body_required,
            ))

    return results
