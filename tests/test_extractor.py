from src.extractor import extract_specs, extract_auth_specs


def _openapi_with_array_of_objects() -> dict:
    return {
        "openapi": "3.1.0",
        "paths": {
            "/carts": {
                "post": {
                    "operationId": "createCart",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["lines"],
                                    "properties": {
                                        "lines": {
                                            "type": "array",
                                            "minItems": 1,
                                            "items": {
                                                "type": "object",
                                                "required": ["sku", "qty"],
                                                "properties": {
                                                    "sku": {"type": "string", "minLength": 3},
                                                    "qty": {"type": "integer", "minimum": 1},
                                                },
                                            },
                                        }
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        },
    }


def test_array_items_object_properties_are_flattened():
    _, body_specs = extract_specs(_openapi_with_array_of_objects())
    field_paths = {s["fieldPath"] for s in body_specs}
    assert "lines" in field_paths
    assert "lines[].sku" in field_paths
    assert "lines[].qty" in field_paths


def test_array_item_field_required_flag_from_item_schema():
    _, body_specs = extract_specs(_openapi_with_array_of_objects())
    sku_spec = next(s for s in body_specs if s["fieldPath"] == "lines[].sku")
    assert sku_spec["required"] is True


def test_array_of_primitives_not_flattened_further():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/tags": {
                "post": {
                    "operationId": "createTags",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    field_paths = {s["fieldPath"] for s in body_specs}
    assert "tags" in field_paths
    assert not any(p.startswith("tags[]") for p in field_paths)


def test_auth_specs_extracted_for_bearer_scheme():
    api = {
        "openapi": "3.1.0",
        "security": [{"BearerAuth": []}],
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": {
            "/me": {
                "get": {"operationId": "getMe", "responses": {"200": {"description": "OK"}}},
            }
        },
    }
    specs = extract_auth_specs(api)
    assert len(specs) == 1
    assert specs[0]["schemeType"] == "bearer"
    assert specs[0]["headerName"] == "Authorization"
