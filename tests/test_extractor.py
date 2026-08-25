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


def test_operation_level_parameter_overrides_path_level_parameter():
    # OpenAPI の仕様上、同じ name/in の組み合わせは operation 階層が path 階層を
    # 上書きする。単純結合すると上書きされたはずの古い定義（string の id）も
    # 残ってしまい、矛盾したテストケースが生成されていた。
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/items/{id}": {
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "get": {
                    "operationId": "getItem",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }
    param_specs, _ = extract_specs(api)
    id_specs = [s for s in param_specs if s["name"] == "id" and s["in"] == "path"]
    assert len(id_specs) == 1
    assert id_specs[0]["schema"]["type"] == "integer"


def test_path_level_parameter_kept_when_not_overridden():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/items/{id}": {
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "get": {"operationId": "getItem", "responses": {"200": {"description": "OK"}}},
            }
        },
    }
    param_specs, _ = extract_specs(api)
    id_specs = [s for s in param_specs if s["name"] == "id" and s["in"] == "path"]
    assert len(id_specs) == 1
    assert id_specs[0]["schema"]["type"] == "string"


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


def test_auth_specs_basic_scheme():
    api = {
        "openapi": "3.1.0",
        "security": [{"BasicAuth": []}],
        "components": {"securitySchemes": {"BasicAuth": {"type": "http", "scheme": "basic"}}},
        "paths": {"/me": {"get": {"operationId": "getMe", "responses": {"200": {"description": "OK"}}}}},
    }
    specs = extract_auth_specs(api)
    assert specs[0]["schemeType"] == "basic"


def test_auth_specs_api_key_scheme_uses_custom_header_name():
    api = {
        "openapi": "3.1.0",
        "security": [{"ApiKeyAuth": []}],
        "components": {
            "securitySchemes": {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}
        },
        "paths": {"/me": {"get": {"operationId": "getMe", "responses": {"200": {"description": "OK"}}}}},
    }
    specs = extract_auth_specs(api)
    assert specs[0]["schemeType"] == "apiKey"
    assert specs[0]["headerName"] == "X-Api-Key"


def test_auth_specs_skips_empty_path_item():
    api = {"openapi": "3.1.0", "paths": {"/empty": None}}
    assert extract_auth_specs(api) == []


def test_auth_specs_skips_empty_security_requirement():
    # security: [{}] は「無条件で許可」を表し、スキーム名が取れないため対象外
    api = {
        "openapi": "3.1.0",
        "security": [{}],
        "paths": {"/me": {"get": {"operationId": "getMe", "responses": {"200": {"description": "OK"}}}}},
    }
    assert extract_auth_specs(api) == []


def test_auth_specs_operation_level_security_overrides_global():
    api = {
        "openapi": "3.1.0",
        "security": [{"BearerAuth": []}],
        "components": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer"}}},
        "paths": {
            "/public": {
                "get": {"operationId": "getPublic", "security": [], "responses": {"200": {"description": "OK"}}}
            }
        },
    }
    # operation 側で security: [] を明示 → 認証不要としてスキップ
    assert extract_auth_specs(api) == []


# --- extract_specs: 分岐カバレッジ ---


def test_extract_specs_skips_empty_path_item():
    api = {"openapi": "3.1.0", "paths": {"/empty": None}}
    param_specs, body_specs = extract_specs(api)
    assert param_specs == []
    assert body_specs == []


def test_extract_specs_skips_param_missing_name():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "get": {
                    "operationId": "getX",
                    "parameters": [{"in": "query", "schema": {"type": "string"}}],  # name なし
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    param_specs, _ = extract_specs(api)
    assert param_specs == []


def test_extract_specs_skips_binary_format_param():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "get": {
                    "operationId": "getX",
                    "parameters": [
                        {"name": "file", "in": "query", "schema": {"type": "string", "format": "binary"}}
                    ],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    param_specs, _ = extract_specs(api)
    assert param_specs == []


def test_extract_specs_skips_non_json_request_body():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "post": {
                    "operationId": "postX",
                    "requestBody": {"content": {"multipart/form-data": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    assert body_specs == []


def test_extract_specs_skips_request_body_with_no_schema():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "post": {
                    "operationId": "postX",
                    "requestBody": {"content": {"application/json": {}}},
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    assert body_specs == []


def test_extract_specs_nested_object_property_recursion():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "customer": {
                                            "type": "object",
                                            "required": ["name"],
                                            "properties": {"name": {"type": "string"}},
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
    _, body_specs = extract_specs(api)
    field_paths = {s["fieldPath"] for s in body_specs}
    assert "customer" in field_paths
    assert "customer.name" in field_paths
    name_spec = next(s for s in body_specs if s["fieldPath"] == "customer.name")
    assert name_spec["required"] is True


def test_extract_specs_skips_binary_format_body_field():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "post": {
                    "operationId": "postX",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"file": {"type": "string", "format": "binary"}},
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    assert not any(s["fieldPath"] == "file" for s in body_specs)


def test_extract_specs_skips_readonly_body_field():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "post": {
                    "operationId": "postX",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer", "readOnly": True},
                                        "name": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    assert not any(s["fieldPath"] == "id" for s in body_specs)
    assert any(s["fieldPath"] == "name" for s in body_specs)


def test_extract_specs_skips_readonly_nested_object_and_its_children():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "post": {
                    "operationId": "postX",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "meta": {
                                            "type": "object",
                                            "readOnly": True,
                                            "properties": {"createdAt": {"type": "string"}},
                                        },
                                        "name": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    _, body_specs = extract_specs(api)
    assert not any(s["fieldPath"] == "meta" for s in body_specs)
    assert not any(s["fieldPath"] == "meta.createdAt" for s in body_specs)
    assert any(s["fieldPath"] == "name" for s in body_specs)


def test_operation_id_fallback_when_missing():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/users/{id}/posts": {
                "get": {
                    "parameters": [{"name": "id", "in": "path", "schema": {"type": "integer"}}],
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    param_specs, _ = extract_specs(api)
    # operationId 未指定 → {METHOD}_{PATH_NORMALIZED} 形式にフォールバックする
    assert param_specs[0]["operationId"] == "GET_users_id_posts"


def test_success_status_defaults_to_200_when_no_responses():
    api = {
        "openapi": "3.1.0",
        "paths": {"/x": {"get": {"operationId": "getX", "parameters": [
            {"name": "q", "in": "query", "schema": {"type": "string"}}
        ]}}},
    }
    param_specs, _ = extract_specs(api)
    assert param_specs[0]["successStatus"] == "200"
    assert param_specs[0]["responsesInfo"] == {}
