import json
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


OPENAPI_WITH_DEFAULT = {
    "paths": {
        "/users/{id}": {
            "get": {
                "operationId": "getUser",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "properties": {"id": {"type": "integer"}}}
                            }
                        }
                    },
                    "default": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["message"],
                                    "properties": {"message": {"type": "string"}},
                                }
                            }
                        }
                    },
                },
            }
        }
    }
}


def test_resolve_response_schema_falls_back_to_default_for_unlisted_status():
    # 個別のステータス（例: 500）が明示されていなくても、"default" にスキーマがあれば
    # それを使う（OpenAPIの標準的なエラーレスポンスの書き方）。
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "500", OPENAPI_WITH_DEFAULT)
    assert schema is not None
    assert schema["required"] == ["message"]


def test_resolve_response_schema_prefers_explicit_status_over_default():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", OPENAPI_WITH_DEFAULT)
    assert schema is not None
    assert "message" not in (schema.get("properties") or {})


# --- resolve_response_schema: writeOnly を任意・禁止項目へ変換 ---

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


def test_resolve_response_schema_makes_write_only_top_level_optional_and_forbidden():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    assert schema["properties"]["password"]["x-api-tester-write-only"] is True
    assert "password" not in schema["required"]
    assert "id" in schema["properties"]


def test_resolve_response_schema_makes_nested_write_only_optional_and_forbidden():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    profile = schema["properties"]["profile"]
    assert profile["properties"]["secretToken"]["x-api-tester-write-only"] is True
    assert "secretToken" not in profile["required"]
    assert "nickname" in profile["properties"]


def test_resolve_response_schema_preserves_write_only_rule_inside_array_items():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    item_props = schema["properties"]["tags"]["items"]["properties"]
    assert item_props["internalNote"]["x-api-tester-write-only"] is True
    assert "label" in item_props


def test_resolve_response_schema_preserves_write_only_rules_inside_additional_properties():
    # additionalProperties がスキーマ（動的キーの値の形を定義）の場合も再帰すること。
    # ここを見落とすと、動的キー側にネストした writeOnly な必須プロパティが required に
    # 残ったままになり、実際には正しく省略されているレスポンスを誤ってNG判定してしまう。
    openapi = {
        "paths": {
            "/reports": {
                "get": {
                    "operationId": "getReports",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "additionalProperties": {
                                            "type": "object",
                                            "required": ["name", "debugSecret"],
                                            "properties": {
                                                "name": {"type": "string"},
                                                "debugSecret": {"type": "string", "writeOnly": True},
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
    schema = resolve_response_schema("getReports", "/reports", "GET", "200", openapi)
    additional = schema["additionalProperties"]
    assert additional["properties"]["debugSecret"]["x-api-tester-write-only"] is True
    assert "debugSecret" not in additional["required"]
    assert "name" in additional["properties"]

    # 実際にwriteOnlyフィールドを含まないレスポンスがNG判定されないことも確認する
    errors = validate_body('{"item1": {"name": "a"}}', schema)
    assert errors == []

    errors = validate_body('{"item1": {"name": "a", "debugSecret": "hidden-value"}}', schema)
    assert errors == ["item1/debugSecret: writeOnlyフィールドがレスポンスに含まれています"]
    assert "hidden-value" not in " ".join(errors)


def test_resolve_response_schema_write_only_handling_does_not_mutate_original():
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


def test_write_only_values_in_response_fail_without_copying_secrets_into_errors():
    schema = resolve_response_schema("getUser", "/users/{id}", "GET", "200", WRITE_ONLY_OPENAPI)
    body = json.dumps({
        "id": 1,
        "password": "top-secret-password",
        "profile": {"nickname": "太郎", "secretToken": "nested-secret-token"},
        "tags": [{"label": "a", "internalNote": "private-note"}],
    })

    errors = validate_body(body, schema)

    assert errors
    assert all("writeOnly" in error for error in errors)
    assert "top-secret-password" not in " ".join(errors)
    assert "nested-secret-token" not in " ".join(errors)
    assert "private-note" not in " ".join(errors)


def test_write_only_rules_are_preserved_in_one_of_variants():
    # _oneOfVariants に退避された各バリアントにも writeOnly 禁止条件が及ぶこと
    # （及ばないと、2番目以降のバリアントで検証した際に誤って writeOnly フィールドを
    # 必須として要求してしまう）。
    openapi = {
        "paths": {
            "/contacts": {
                "get": {
                    "operationId": "getContact",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["kind", "email"],
                                        "properties": {
                                            "kind": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "_oneOfVariants": [
                                            {
                                                "type": "object",
                                                "required": ["kind", "email"],
                                                "properties": {
                                                    "kind": {"type": "string"},
                                                    "email": {"type": "string"},
                                                },
                                            },
                                            {
                                                "type": "object",
                                                "required": ["kind", "phone", "internalNote"],
                                                "properties": {
                                                    "kind": {"type": "string"},
                                                    "phone": {"type": "string"},
                                                    "internalNote": {"type": "string", "writeOnly": True},
                                                },
                                            },
                                        ],
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    schema = resolve_response_schema("getContact", "/contacts", "GET", "200", openapi)
    second_variant = schema["_oneOfVariants"][1]
    assert second_variant["properties"]["internalNote"]["x-api-tester-write-only"] is True
    assert "internalNote" not in second_variant["required"]

    errors = validate_body('{"kind": "phone", "phone": "090-1234-5678"}', schema)
    assert errors == []

    errors = validate_body(
        '{"kind": "phone", "phone": "090-1234-5678", "internalNote": "variant-secret"}',
        schema,
    )
    assert any("writeOnlyフィールドがレスポンスに含まれています" in error for error in errors)
    assert "variant-secret" not in " ".join(errors)


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


# --- oneOf/anyOf のバリアント検証 ---
# parser.py が残す _oneOfVariants（代表バリアント以外も含む正規化済みスキーマ一覧）に
# 基づき、いずれか1バリアントに適合すれば OK とする回帰テスト。

ONE_OF_SCHEMA = {
    "type": "object",
    "required": ["kind"],
    "properties": {"kind": {"type": "string"}},
    "_oneOfVariants": [
        {"type": "object", "required": ["kind", "email"], "properties": {"kind": {"type": "string"}, "email": {"type": "string"}}},
        {"type": "object", "required": ["kind", "phone"], "properties": {"kind": {"type": "string"}, "phone": {"type": "string"}}},
    ],
}


def test_validate_body_matches_first_variant_passes():
    errors = validate_body('{"kind": "email", "email": "a@example.com"}', ONE_OF_SCHEMA)
    assert errors == []


def test_validate_body_matches_second_variant_passes():
    # 平坦化された schema（1番目のバリアント形状）には email しか無いが、
    # 実際のレスポンスが2番目のバリアント（phone）形状でも正当にOKとなること。
    errors = validate_body('{"kind": "phone", "phone": "090-1234-5678"}', ONE_OF_SCHEMA)
    assert errors == []


def test_validate_body_matches_no_variant_fails_with_first_variant_errors():
    errors = validate_body('{"kind": "fax"}', ONE_OF_SCHEMA)
    assert len(errors) >= 2
    assert "2 件のバリアント" in errors[0]


def test_validate_body_without_one_of_variants_still_validates_flat_schema():
    # _oneOfVariants を持たない従来のスキーマは今まで通り単一スキーマとして検証される
    errors = validate_body('{"id": 1, "name": "Alice"}', SCHEMA)
    assert errors == []
