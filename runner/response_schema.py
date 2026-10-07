from __future__ import annotations
import re
from models import RunCase, ResponseSchema
from response_validator import resolve_response_schema

_TIME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*秒")
_EXISTENCE_ONLY_MARKER = "（存在確認のみ）"


def from_run_case(case: RunCase, openapi: dict | None = None) -> ResponseSchema:
    status_class = _parse_status_class(case.expected_status)
    status = None if status_class is not None else _parse_status(case.expected_status)
    content_type = _parse_content_type(case.expected_response_header)
    expected_headers = _parse_expected_headers(case.expected_response_header)
    response_time_ms = _parse_time_ms(case.expected_response_time)
    expected_statuses: frozenset[int] = frozenset()
    body_schemas_by_status: dict[int, dict | None] = {}
    content_types_by_status: dict[int, frozenset[str]] = {}
    header_schemas_by_status: dict[int, dict[str, dict]] = {}
    header_names_by_status: dict[int, frozenset[str]] = {}
    body_schemas_by_status_and_content_type: dict[int, dict[str, dict]] = {}
    if openapi is not None:
        operation = _find_operation(openapi, case)
        responses = operation.get("responses") or {} if operation else {}
        has_status_range = any(str(code).upper() == "2XX" for code in responses)
        if status_class == 2:
            expected_statuses = frozenset(
                int(code) for code in responses
                if str(code).isdigit() and 200 <= int(code) < 300
            )
            if has_status_range:
                expected_statuses = frozenset()
        elif status_class == 4:
            preferred = {400, 422}
            if case.param_in == "path":
                preferred.add(404)
            expected_statuses = frozenset(
                int(code) for code in responses
                if str(code).isdigit() and int(code) in preferred
            )
        status_codes = set(expected_statuses) or (
            set(range(200, 300)) if status_class == 2 and has_status_range else set()
        ) or (
            frozenset({status}) if status is not None else frozenset()
        )
        for code in status_codes:
            response = _response_for_status(responses, code)
            content = response.get("content") or {}
            if content:
                content_types_by_status[code] = frozenset(str(name) for name in content)
                json_schemas = {}
                for media_type in content:
                    normalized_media_type = str(media_type).split(";", 1)[0].strip().lower()
                    if normalized_media_type == "application/json" or normalized_media_type.endswith("+json"):
                        media_schema = resolve_response_schema(
                            case.operation_id, case.path, case.method, str(code), openapi,
                            content_type=str(media_type),
                        )
                        if media_schema is not None:
                            json_schemas[str(media_type)] = media_schema
                if json_schemas:
                    body_schemas_by_status_and_content_type[code] = json_schemas
            response_headers = response.get("headers") or {}
            header_schemas = {
                name: header
                for name, header in response_headers.items()
                if isinstance(header, dict) and isinstance(header.get("schema"), dict)
            }
            if header_schemas:
                header_schemas_by_status[code] = header_schemas
            required_header_names = frozenset(
                str(name) for name, header in response_headers.items()
                if isinstance(header, dict) and header.get("required", False)
            )
            if required_header_names:
                header_names_by_status[code] = required_header_names
            schema = resolve_response_schema(
                case.operation_id, case.path, case.method, str(code), openapi,
            )
            # Keep a per-status None entry as well. It distinguishes a documented no-body or
            # non-JSON response from an unknown status that may use the default response schema.
            body_schemas_by_status[code] = schema
    body_schema = (
        resolve_response_schema(case.operation_id, case.path, case.method, case.expected_status, openapi)
        if openapi is not None and (status is not None or status_class is not None)
        else None
    )
    return ResponseSchema(
        expected_status=status,
        expected_content_type=content_type,
        expected_response_time_ms=response_time_ms,
        expected_body_schema=body_schema,
        expected_status_class=status_class,
        expected_statuses=expected_statuses,
        expected_body_schemas_by_status=body_schemas_by_status,
        expected_body_schemas_by_status_and_content_type=body_schemas_by_status_and_content_type,
        expected_content_types_by_status=content_types_by_status,
        expected_header_schemas_by_status=header_schemas_by_status,
        expected_header_names_by_status=header_names_by_status,
        expected_headers=expected_headers,
    )


def _parse_status(raw: str) -> int | None:
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _parse_status_class(raw: str) -> int | None:
    match = re.fullmatch(r"([1-5])xx", raw.strip().lower())
    return int(match.group(1)) if match else None


def _find_operation(openapi: dict, case: RunCase) -> dict | None:
    paths = openapi.get("paths", {})
    path_item = paths.get(case.path)
    if path_item is None:
        for candidate in paths.values():
            if any(
                isinstance(operation, dict) and operation.get("operationId") == case.operation_id
                for operation in candidate.values()
            ):
                path_item = candidate
                break
    if not isinstance(path_item, dict):
        return None
    operation = path_item.get(case.method.lower())
    return operation if isinstance(operation, dict) else None


def _response_for_status(responses: dict, status: int) -> dict:
    response = responses.get(str(status))
    if response is not None:
        return response
    response = next(
        (value for code, value in responses.items() if str(code).upper() == f"{status // 100}XX"),
        None,
    )
    return response or responses.get("default") or {}


def _parse_content_type(raw: str) -> str | None:
    for line in raw.splitlines():
        if line.lower().startswith("content-type:"):
            value = line.split(":", 1)[1].strip()
            # exclude placeholder values
            if "複数" in value or "要確認" in value:
                return None
            return value
    return None


def _parse_expected_headers(raw: str) -> dict:
    """expectedResponseHeader列からContent-Type以外のヘッダ期待値を取り出す。

    値が「（存在確認のみ）」（generatorがOpenAPI定義のheadersセクションから機械的に
    出力するマーカー。具体的な値まではOpenAPI定義から確実には分からないため）の場合は
    ヘッダの存在確認のみを行う（値は None として保持する）。
    """
    headers: dict[str, str | None] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip()
        value = value.strip()
        if not name or name.lower() == "content-type":
            continue
        if value == _EXISTENCE_ONLY_MARKER or "複数" in value or "要確認" in value:
            headers[name] = None
        else:
            headers[name] = value
    return headers


def _parse_time_ms(raw: str) -> float:
    m = _TIME_PATTERN.search(raw)
    if m:
        return float(m.group(1)) * 1000
    return 3000.0  # default 3 seconds
