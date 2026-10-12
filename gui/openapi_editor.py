"""UI helpers for filling in JSON request/response body contracts in OpenAPI files."""
from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from src.parser import OpenAPIParseError, parse_openapi
from src.db_scope import KEY as DB_KEY, validate_scopes

_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_SUCCESS_STATUS = re.compile(r"(?:2\d\d|2XX)", re.IGNORECASE)
_JSON_MEDIA_TYPE = "application/json"


def load_operation_body_contract(path: str, operation_id: str) -> dict:
    """Load the editable JSON body schemas for one operation without normalizing the file."""
    document = _read_document(path)
    _, _, operation = _find_operation(document, operation_id)

    request_body = _dereference_object(document, operation.get("requestBody"))
    request_schema = _schema_from_json_content((request_body.get("content") or {}))

    responses = operation.get("responses") or {}
    response_status = _preferred_success_status(responses)
    response_key = _response_key(responses, response_status)
    response = _dereference_object(document, responses.get(response_key) if response_key else None)
    if not response:
        response = _dereference_object(document, _range_response(responses, response_status))
    response_schema = _schema_from_json_content(response.get("content") or {})

    return {
        "operationId": operation_id,
        "requestBodyRequired": bool(request_body.get("required", False)),
        "requestBodySchema": request_schema,
        "responseStatus": response_status,
        "responseBodySchema": response_schema,
        "responseBodyEmpty": bool(response) and not response.get("content"),
        "errorDbUnchanged": operation.get(DB_KEY, []),
    }


def save_operation_body_contract(
    source_path: str,
    destination_path: str,
    operation_id: str,
    request_body_required: bool,
    request_body_schema: dict | None,
    response_status: str,
    response_body_schema: dict | None,
    error_db_unchanged: list | None = None,
    response_body_empty: bool = False,
) -> dict:
    """Save edited schemas to a validated copy; never overwrite the selected source file."""
    source = Path(source_path).expanduser().resolve()
    destination = Path(destination_path).expanduser().resolve()
    if source == destination:
        raise ValueError("元のopenapi.jsonを上書きできません。別名で保存してください")
    if not isinstance(request_body_required, bool):
        raise ValueError("リクエストボディの必須設定が不正です")
    _validate_schema_value(request_body_schema, "リクエストボディschema")
    _validate_schema_value(response_body_schema, "レスポンスボディschema")

    status = str(response_status).strip().upper()
    if not _SUCCESS_STATUS.fullmatch(status):
        raise ValueError("レスポンスstatusは200〜299または2XXで指定してください")

    document = _read_document(str(source))
    _, _, operation = _find_operation(document, operation_id)

    if error_db_unchanged is not None:
        operation[DB_KEY] = validate_scopes(error_db_unchanged)

    raw_request_body = operation.get("requestBody")
    if raw_request_body is not None or request_body_schema is not None or request_body_required:
        request_body = _dereference_object(document, raw_request_body)
        request_content = request_body.get("content")
        if not isinstance(request_content, dict):
            request_content = {}
        _set_json_schema(request_content, request_body_schema)
        request_body["content"] = request_content
        request_body["required"] = request_body_required
        operation["requestBody"] = request_body

    responses = operation.get("responses")
    if not isinstance(responses, dict):
        responses = {}
    if type(response_body_empty) is not bool:
        raise ValueError("レスポンスボディなしの設定は真偽値で指定してください")
    if response_body_empty:
        response_key = _response_key(responses, status)
        response = _dereference_object(document, responses.get(response_key) if response_key else None)
        response = response or {"description": "No response body"}
        response.pop("content", None)
        responses[response_key or status] = response
    elif response_body_schema is not None:
        response_key = _response_key(responses, status)
        response = _dereference_object(document, responses.get(response_key) if response_key else None)
        if not response:
            response = {"description": "Edited in API Test Generator"}
        response_content = response.get("content")
        if not isinstance(response_content, dict):
            response_content = {}
        _set_json_schema(response_content, response_body_schema)
        response["content"] = response_content
        responses[response_key or status] = response
    operation["responses"] = responses

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            json.dump(document, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")

        parsed = parse_openapi(str(temp_path))
        _validate_saved_schemas(parsed, operation_id, status)
        os.replace(temp_path, destination)
    except (OSError, OpenAPIParseError, SchemaError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"OpenAPIの保存・検証に失敗しました: {error}") from error
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return {
        "path": str(destination),
        "operationId": operation_id,
        "responseStatus": status,
    }


def _read_document(path: str) -> dict:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"openapi.jsonを読み込めません: {error}") from error
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
        raise ValueError("OpenAPI 3.x形式のJSONを指定してください")
    return document


def _find_operation(document: dict, operation_id: str) -> tuple[str, str, dict]:
    matches = []
    for path, path_item in (document.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if (
                method.lower() in _HTTP_METHODS
                and isinstance(operation, dict)
                and operation.get("operationId") == operation_id
            ):
                matches.append((path, method.lower(), operation))
    if len(matches) != 1:
        raise ValueError("operationIdが見つからないか、重複しています")
    return matches[0]


def _lookup_local_ref(document: dict, reference: str) -> object:
    if not reference.startswith("#/"):
        raise ValueError("外部$refはUI編集に対応していません")
    value: object = document
    for part in reference[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"$refを解決できません: {reference}")
        value = value[key]
    return value


def _dereference_object(document: dict, value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    current = copy.deepcopy(value)
    seen: set[str] = set()
    while isinstance(current, dict) and "$ref" in current:
        reference = current["$ref"]
        if not isinstance(reference, str) or reference in seen:
            raise ValueError("循環参照または不正な$refがあります")
        seen.add(reference)
        target = _lookup_local_ref(document, reference)
        if not isinstance(target, dict):
            raise ValueError(f"$refの参照先がオブジェクトではありません: {reference}")
        siblings = {key: child for key, child in current.items() if key != "$ref"}
        current = copy.deepcopy(target)
        current.update(siblings)
    return current


def _schema_from_json_content(content: dict) -> dict | None:
    media = content.get(_JSON_MEDIA_TYPE)
    if not isinstance(media, dict):
        return None
    schema = media.get("schema")
    return copy.deepcopy(schema) if isinstance(schema, dict) else None


def _preferred_success_status(responses: dict) -> str:
    codes = [str(code) for code in responses if str(code).isdigit() and 200 <= int(code) < 300]
    for preferred in ("200", "201"):
        if preferred in codes:
            return preferred
    if codes:
        return sorted(codes, key=int)[0]
    if _range_response(responses, "200"):
        return next(str(code).upper() for code in responses if str(code).upper() == "2XX")
    return "200"


def _range_response(responses: dict, status: str) -> dict | None:
    if not status.isdigit():
        return None
    return next(
        (value for code, value in responses.items() if str(code).upper() == f"{int(status) // 100}XX"),
        None,
    )


def _response_key(responses: dict, status: str) -> object | None:
    return next(
        (code for code in responses if str(code).upper() == status.upper()),
        None,
    )


def _set_json_schema(content: dict, schema: dict | None) -> None:
    media = content.get(_JSON_MEDIA_TYPE)
    if schema is None:
        if isinstance(media, dict):
            media.pop("schema", None)
        return
    if not isinstance(media, dict):
        media = {}
    media["schema"] = copy.deepcopy(schema)
    content[_JSON_MEDIA_TYPE] = media


def _validate_schema_value(schema: dict | None, label: str) -> None:
    if schema is not None and not isinstance(schema, dict):
        raise ValueError(f"{label}はJSONオブジェクトで指定してください")


def _validate_saved_schemas(document: dict, operation_id: str, status: str) -> None:
    _, _, operation = _find_operation(document, operation_id)
    responses = operation.get("responses") or {}
    response_key = _response_key(responses, status)
    schemas = [
        ((operation.get("requestBody") or {}).get("content") or {}).get(_JSON_MEDIA_TYPE, {}).get("schema"),
        ((((responses.get(response_key) if response_key else {}) or {}).get("content") or {})
         .get(_JSON_MEDIA_TYPE, {}).get("schema")),
    ]
    for schema in schemas:
        if isinstance(schema, dict):
            Draft202012Validator.check_schema(schema)
