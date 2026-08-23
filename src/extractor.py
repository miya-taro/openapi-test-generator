"""OpenAPI ドキュメントから ParamSpec / BodyFieldSpec / AuthSpec を抽出する。"""
from __future__ import annotations
import re

from . import logger as log

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

            first_scheme_name = next(iter(op_security[0]), None) if op_security else None
            if not first_scheme_name:
                continue

            scheme = security_schemes.get(first_scheme_name, {}) or {}
            scheme_type = "other"
            header_name = "Authorization"

            if scheme.get("type") == "http" and scheme.get("scheme") == "bearer":
                scheme_type = "bearer"
            elif scheme.get("type") == "http" and scheme.get("scheme") == "basic":
                scheme_type = "basic"
            elif scheme.get("type") == "apiKey":
                scheme_type = "apiKey"
                header_name = scheme.get("name") or "X-Api-Key"

            operation_id = _resolve_operation_id(operation, method, path)
            success_status = _resolve_success_status(operation.get("responses"))
            responses_info = _build_responses_info(operation.get("responses"))

            specs.append({
                "operationId": operation_id,
                "path": path,
                "method": method.upper(),
                "schemeType": scheme_type,
                "headerName": header_name,
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

            parameters = [
                *(path_item.get("parameters") or []),
                *(operation.get("parameters") or []),
            ]

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
                json_content = (request_body.get("content") or {}).get("application/json")
                if not json_content:
                    log.debug({"operationId": operation_id}, "application/json 以外の requestBody をスキップ")
                    continue

                body_schema = json_content.get("schema")
                if not body_schema:
                    continue

                fields = _flatten_body_schema(
                    body_schema, "", operation_id, path, method.upper(), success_status, responses_info
                )
                body_specs.extend(fields)

    return param_specs, body_specs


def _resolve_success_status(responses: dict | None) -> str:
    if not responses:
        return "200"
    success_codes = sorted(code for code in responses if re.fullmatch(r"2\d\d", code))
    return success_codes[0] if success_codes else "200"


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


def _flatten_body_schema(
    schema: dict,
    parent_path: str,
    operation_id: str,
    path: str,
    method: str,
    success_status: str,
    responses_info: dict,
) -> list[dict]:
    results: list[dict] = []

    if schema.get("type") == "object" or "properties" in schema:
        required_fields = set(schema.get("required") or [])
        properties = schema.get("properties") or {}

        # オブジェクト自体のスペック（空body チェック等に使う）
        if parent_path == "":
            results.append({
                "operationId": operation_id,
                "path": path,
                "method": method,
                "fieldPath": "__body__",
                "required": True,
                "schema": schema,
                "successStatus": success_status,
                "responsesInfo": responses_info,
            })

        for prop_name, prop_schema in properties.items():
            if not prop_schema:
                continue

            field_path = f"{parent_path}.{prop_name}" if parent_path else prop_name

            if prop_schema.get("format") == "binary":
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
            })

            # ネストされたオブジェクトを再帰的に展開
            if prop_schema.get("type") == "object" or "properties" in prop_schema:
                results.extend(
                    _flatten_body_schema(
                        prop_schema, field_path, operation_id, path, method, success_status, responses_info
                    )
                )

            # 配列の要素がオブジェクトの場合、その要素のプロパティも再帰的に展開する
            # （フィールドパスは "lines[].sku" のように "[]" で配列であることを表す）
            elif prop_schema.get("type") == "array":
                items_schema = prop_schema.get("items")
                if isinstance(items_schema, dict) and (
                    items_schema.get("type") == "object" or "properties" in items_schema
                ):
                    results.extend(
                        _flatten_body_schema(
                            items_schema,
                            f"{field_path}[]",
                            operation_id,
                            path,
                            method,
                            success_status,
                            responses_info,
                        )
                    )

    return results
