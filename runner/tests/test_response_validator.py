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


# --- resolve_response_schema: writeOnly の除去 ---

WRITE_ONLY_OPENAPI = {
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
                                    "required": ["id", "password"],
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "password": {"type": "string", "writeOnly": True},
                                        "profile": {
                                            "type": "object",
                                            "required": ["secretToken"],
                                            "properties": {
                                                "secretToken": {"type": "string", "writeOnly": True},
                                                "nickname": {"type": "string"},
                                            },
                                        },
                                        "tags": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "internalNote": {"type": "string", "writeOnly": True},
                                                    "label": {"type": "string"},
                                                },
                                            },
                                        },
                                    },
                                }
                            }
                        }
                    }
                },
            }
        }
    }
}


def test_resolve_response_schema_strips_write_only_top_level_property():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    assert "password" not in schema["properties"]
    assert "password" not in schema["required"]
    assert "id" in schema["properties"]


def test_resolve_response_schema_strips_write_only_nested_property():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    profile = schema["properties"]["profile"]
    assert "secretToken" not in profile["properties"]
    assert "secretToken" not in profile["required"]
    assert "nickname" in profile["properties"]


def test_resolve_response_schema_strips_write_only_inside_array_items():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    item_props = schema["properties"]["tags"]["items"]["properties"]
    assert "internalNote" not in item_props
    assert "label" in item_props


def test_resolve_response_schema_write_only_stripping_does_not_mutate_original():
    resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    original_props = (
        WRITE_ONLY_OPENAPI["paths"]["/users/{id}"]["get"]["responses"]["200"]
        ["content"]["application/json"]["schema"]["properties"]
    )
    assert "password" in original_props  # 元のopenapiドキュメントは変更されていないこと


def test_write_only_field_missing_in_actual_response_does_not_fail_validation():
    # サーバーがwriteOnlyフィールドをレスポンスに含めなくても、requiredから除外済みなので合格する
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    errors = validate_body('{"id": 1, "profile": {"nickname": "太郎"}}', schema)
    assert errors == []


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
