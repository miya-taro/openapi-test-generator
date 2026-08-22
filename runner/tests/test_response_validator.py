import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from response_validator import resolve_response_schema, validate_body


OPENAPI = {
    "paths": {
        "/users/{id}": {
            "get": {
                "operationId": "getUser",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["id", "name"],
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "name": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "404": {"description": "Not Found"},
                },
            }
        }
    }
}


# --- resolve_response_schema ---


def test_resolve_response_schema_found():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", OPENAPI)
    assert schema is not None
    assert schema["required"] == ["id", "name"]


def test_resolve_response_schema_no_content_returns_none():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "404", OPENAPI)
    assert schema is None


def test_resolve_response_schema_unknown_status_returns_none():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "500", OPENAPI)
    assert schema is None


def test_resolve_response_schema_by_operation_id_when_path_differs():
    schema = resolve_response_schema("getUser", "/does/not/match", "GET", "200", OPENAPI)
    assert schema is not None


# --- validate_body ---

SCHEMA = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
}


def test_validate_body_no_schema_always_passes():
    assert validate_body("not even json", None) == []


def test_validate_body_valid_body_passes():
    assert validate_body('{"id": 1, "name": "Alice"}', SCHEMA) == []


def test_validate_body_missing_required_field_fails():
    errors = validate_body('{"id": 1}', SCHEMA)
    assert len(errors) == 1
    assert "name" in errors[0]


def test_validate_body_wrong_type_fails():
    errors = validate_body('{"id": "not-an-int", "name": "Alice"}', SCHEMA)
    assert len(errors) == 1


def test_validate_body_invalid_json_fails():
    errors = validate_body("{not valid json", SCHEMA)
    assert len(errors) == 1
    assert "JSON" in errors[0]


def test_validate_body_empty_body_fails_when_schema_declared():
    errors = validate_body("", SCHEMA)
    assert len(errors) == 1
