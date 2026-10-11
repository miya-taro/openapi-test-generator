#!/usr/bin/env python3
"""A local HTTP target that enforces the request and response contract fixture.

This API deliberately has no persistence or business rules. It loads
validation_openapi.json, validates incoming parameters and JSON bodies against
their OpenAPI schemas, and returns a schema-valid example response. It exists
to exercise the generator and HTTP runner against a real HTTP server.

Run from the repository root:
    python -m uvicorn docs.validation_api:app --host 127.0.0.1 --port 8081
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from src.schema_example import find_schema_example


SPEC = json.loads(Path(__file__).with_name("validation_openapi.json").read_text(encoding="utf-8"))
FORMAT_CHECKER = FormatChecker()
app = FastAPI(title=SPEC["info"]["title"], docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _match_path(template: str, path: str) -> dict[str, str] | None:
    parts: list[str] = []
    names: list[str] = []
    cursor = 0
    for match in re.finditer(r"\{([^{}]+)\}", template):
        parts.append(re.escape(template[cursor:match.start()]))
        parts.append("([^/]+)")
        names.append(match.group(1))
        cursor = match.end()
    parts.append(re.escape(template[cursor:]))
    match = re.fullmatch("".join(parts), path)
    if match is None:
        return None
    return {name: unquote(value) for name, value in zip(names, match.groups(), strict=True)}


def _find_operation(method: str, path: str):
    for template, path_item in SPEC["paths"].items():
        parameters = list(path_item.get("parameters") or [])
        path_values = _match_path(template, path)
        if path_values is None:
            continue
        operation = path_item.get(method.lower())
        if not isinstance(operation, dict):
            continue
        parameters.extend(operation.get("parameters") or [])
        return operation, parameters, path_values
    return None, [], {}


def _coerce_scalar(raw: str, schema: dict):
    type_ = schema.get("type")
    if type_ == "integer":
        if not re.fullmatch(r"[+-]?(?:0|[1-9][0-9]*)", raw):
            raise ValueError("invalid integer")
        return int(raw)
    if type_ == "number":
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("invalid number")
        return value
    if type_ == "boolean":
        value = raw.lower()
        if value not in {"true", "false"}:
            raise ValueError("invalid boolean")
        return value == "true"
    if type_ in {"object", "array"}:
        return json.loads(raw)
    return raw


def _parameter_value(parameter: dict, request: Request, path_values: dict[str, str]):
    name = parameter["name"]
    location = parameter["in"]
    if location == "path":
        raw_values = [path_values[name]] if name in path_values else []
    elif location == "query":
        raw_values = request.query_params.getlist(name)
    elif location == "header":
        raw = request.headers.get(name)
        raw_values = [] if raw is None else [raw]
    elif location == "cookie":
        raw = request.cookies.get(name)
        raw_values = [] if raw is None else [raw]
    else:
        return None

    if not raw_values:
        if parameter.get("required"):
            raise ValueError(f"missing {location} parameter: {name}")
        return None

    schema = parameter.get("schema") or {}
    if schema.get("type") == "array":
        explode = parameter.get("explode", location == "query")
        raw_items = raw_values if explode else raw_values[0].split(",")
        item_schema = schema.get("items") or {}
        return [_coerce_scalar(value, item_schema) for value in raw_items]
    if schema.get("type") == "object":
        if len(raw_values) != 1:
            raise ValueError("invalid object parameter")
        return _coerce_scalar(raw_values[0], schema)
    if len(raw_values) != 1:
        raise ValueError("multiple values for scalar parameter")
    return _coerce_scalar(raw_values[0], schema)


def _error_response(operation: dict, status: int, message: str) -> JSONResponse:
    response_spec = operation.get("responses", {}).get(str(status), {})
    schema = response_spec.get("content", {}).get("application/json", {}).get("schema", {})
    try:
        body = find_schema_example(schema)
    except ValueError:
        body = {"code": "INVALID_REQUEST", "message": message}
    headers = {"X-Contract-Check": "reject"}
    return JSONResponse(body, status_code=status, headers=headers)


def _success_response(operation: dict) -> JSONResponse:
    status = next(
        (int(code) for code in operation.get("responses", {}) if str(code).isdigit() and 200 <= int(code) < 300),
        200,
    )
    response_spec = operation.get("responses", {}).get(str(status), {})
    schema = response_spec.get("content", {}).get("application/json", {}).get("schema", {})
    body = find_schema_example(schema) if schema else {}
    return JSONResponse(body, status_code=status, headers={"X-Contract-Check": "pass"})


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def validate_contract(request: Request, path: str):
    operation, parameters, path_values = _find_operation(request.method, request.url.path)
    if operation is None:
        return JSONResponse({"detail": "not found"}, status_code=404)

    try:
        for parameter in parameters:
            value = _parameter_value(parameter, request, path_values)
            if value is not None:
                Draft202012Validator(parameter.get("schema") or {}, format_checker=FORMAT_CHECKER).validate(value)

        request_body = operation.get("requestBody") or {}
        if request_body:
            content = request_body.get("content") or {}
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            raw_body = await request.body()
            if not content_type and not raw_body:
                if request_body.get("required"):
                    raise ValueError("request body is required")
                body = None
                selected = None
            else:
                selected = next((value for media_type, value in content.items() if media_type.lower() == content_type), None)
            if selected is None:
                if content and (content_type or raw_body):
                    return _error_response(operation, 415, "Unsupported media type")
            else:
                if not raw_body and request_body.get("required"):
                    raise ValueError("request body is required")
                body = json.loads(raw_body) if raw_body else None
                schema = selected.get("schema") or {}
                Draft202012Validator(schema, format_checker=FORMAT_CHECKER).validate(body)
    except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as error:
        status = 422 if (
            operation.get("operationId") == "createValidationRecord"
            and isinstance(error, ValidationError)
        ) else 400
        return _error_response(operation, status, str(error))

    return _success_response(operation)
