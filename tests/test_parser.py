import json

import pytest

from src.parser import parse_openapi, OpenAPIParseError


def _write(tmp_path, doc: dict) -> str:
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_rejects_non_openapi_3(tmp_path):
    path = _write(tmp_path, {"openapi": "2.0", "paths": {}})
    with pytest.raises(OpenAPIParseError):
        parse_openapi(path)


def test_resolves_internal_ref(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/User"}
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "User": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["paths"]["/users"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object"
    assert schema["properties"]["name"]["type"] == "string"


def test_circular_ref_does_not_hang(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "A": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/A"}}},
            }
        },
    }
    # 無限ループにならず終了すること。$ref は1階層展開したところで循環を検出し打ち切る。
    api = parse_openapi(_write(tmp_path, doc))
    node = api["components"]["schemas"]["A"]["properties"]["child"]["properties"]["child"]
    assert node == {}


def test_shared_non_cyclic_ref_is_resolved_once_and_reused(tmp_path):
    # 循環しない共有スキーマは複数箇所から参照されても同一オブジェクトとして
    # 再利用され（＝再展開されず）、性能上のキャッシュが効いていることを保証する。
    doc = {
        "openapi": "3.1.0",
        "paths": {
            "/a": {"get": {"operationId": "getA", "responses": {
                "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Money"}}}}
            }}},
            "/b": {"get": {"operationId": "getB", "responses": {
                "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Money"}}}}
            }}},
        },
        "components": {
            "schemas": {
                "Money": {"type": "object", "properties": {"amount": {"type": "integer"}}},
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema_a = api["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema_b = api["paths"]["/b"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_a == {"type": "object", "properties": {"amount": {"type": "integer"}}}
    assert schema_a is schema_b


def test_cyclic_ref_referenced_from_two_places_is_not_shared(tmp_path):
    # 循環を含む展開結果はどのスタック経由で辿り着いたかに依存するため、
    # 複数箇所から参照されてもキャッシュを使い回さず、それぞれ独立に展開されること。
    doc = {
        "openapi": "3.1.0",
        "paths": {
            "/a": {"get": {"operationId": "getA", "responses": {
                "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}}
            }}},
            "/b": {"get": {"operationId": "getB", "responses": {
                "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Node"}}}}
            }}},
        },
        "components": {
            "schemas": {
                "Node": {"type": "object", "properties": {"child": {"$ref": "#/components/schemas/Node"}}},
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema_a = api["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema_b = api["paths"]["/b"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema_a["properties"]["child"] == {}
    assert schema_b["properties"]["child"] == {}
    assert schema_a is not schema_b


def test_all_of_merges_properties_and_required(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "allOf": [
                        {
                            "type": "object",
                            "required": ["name"],
                            "properties": {"name": {"type": "string", "minLength": 1}},
                        },
                        {"type": "object", "properties": {"price": {"type": "integer", "minimum": 0}}},
                    ]
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    merged = api["components"]["schemas"]["Item"]
    assert "allOf" not in merged
    assert merged["type"] == "object"
    assert merged["required"] == ["name"]
    assert merged["properties"]["name"]["minLength"] == 1
    assert merged["properties"]["price"]["minimum"] == 0


def test_all_of_inherits_additional_properties_false(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Item": {
                    "allOf": [
                        {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}},
                        {"type": "object", "properties": {"b": {"type": "string"}}},
                    ]
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    merged = api["components"]["schemas"]["Item"]
    assert merged["additionalProperties"] is False


def test_one_of_reduces_to_first_variant(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
                        {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
                    ]
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "oneOf" not in reduced
    assert reduced["required"] == ["name"]
    assert "name" in reduced["properties"]


def test_one_of_discriminator_does_not_corrupt_shared_variant_schema(tmp_path):
    # 回帰テスト: $ref のキャッシュ（性能最適化）により、oneOf の代表バリアントが
    # 別の場所（/a の直接参照）と同一オブジェクトを共有することがある。discriminator
    # 制約の適用が in-place 破壊的だと、無関係な /a 側のスキーマにまで enum 制約が
    # 漏れてしまっていた。
    doc = {
        "openapi": "3.1.0",
        "paths": {
            "/a": {
                "get": {
                    "operationId": "getA",
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Shared"}}}}
                    },
                }
            },
            "/b": {
                "get": {
                    "operationId": "getB",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "oneOf": [
                                            {"$ref": "#/components/schemas/Shared"},
                                            {"type": "object", "title": "Other", "properties": {"kind": {"type": "string"}}},
                                        ],
                                        "discriminator": {"propertyName": "kind"},
                                    }
                                }
                            }
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Shared": {
                    "type": "object",
                    "title": "SharedTitle",
                    "required": ["kind"],
                    "properties": {"kind": {"type": "string"}},
                },
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema_a = api["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    schema_b = api["paths"]["/b"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]

    # /a は Shared への素の参照なので discriminator の enum 制約が付いてはならない
    assert "enum" not in schema_a["properties"]["kind"]
    # /b 側は discriminator により正しく enum 制約が付く
    assert schema_b["properties"]["kind"]["enum"] == ["SharedTitle"]


def test_one_of_preserves_all_variants_for_full_coverage(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
                        {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
                    ]
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    variants = reduced["_oneOfVariants"]
    assert len(variants) == 2
    assert variants[0]["required"] == ["name"]
    assert variants[1]["required"] == ["id"]


def test_one_of_single_variant_does_not_add_sidecar(tmp_path):
    # バリアントが1件しかない場合は「代表以外」が存在しないため _oneOfVariants は不要
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {"oneOf": [{"type": "object", "properties": {"name": {"type": "string"}}}]}
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "_oneOfVariants" not in reduced


def test_any_of_reduces_to_first_variant(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "anyOf": [
                        {"type": "string", "minLength": 1},
                        {"type": "integer"},
                    ]
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "anyOf" not in reduced
    assert reduced["type"] == "string"
    assert reduced["minLength"] == 1


def test_one_of_with_discriminator_constrains_property_using_variant_title(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {
                            "title": "Cat",
                            "type": "object",
                            "required": ["petType"],
                            "properties": {"petType": {"type": "string"}},
                        },
                        {
                            "title": "Dog",
                            "type": "object",
                            "required": ["petType"],
                            "properties": {"petType": {"type": "string"}},
                        },
                    ],
                    "discriminator": {"propertyName": "petType"},
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "discriminator" not in reduced
    assert reduced["properties"]["petType"]["enum"] == ["Cat"]


def test_discriminator_does_not_override_existing_enum(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {
                            "title": "Cat",
                            "type": "object",
                            "properties": {"petType": {"type": "string", "enum": ["cat"]}},
                        },
                    ],
                    "discriminator": {"propertyName": "petType"},
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert reduced["properties"]["petType"]["enum"] == ["cat"]  # 既存のenumは上書きしない


def test_discriminator_without_variant_title_leaves_property_unconstrained(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {"type": "object", "properties": {"petType": {"type": "string"}}},
                    ],
                    "discriminator": {"propertyName": "petType"},
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "enum" not in reduced["properties"]["petType"]


def test_one_of_without_discriminator_unaffected(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {
                "Pet": {
                    "oneOf": [
                        {"title": "Cat", "type": "object", "properties": {"petType": {"type": "string"}}},
                    ],
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    reduced = api["components"]["schemas"]["Pet"]
    assert "enum" not in reduced["properties"]["petType"]


def test_exclusive_minimum_boolean_normalized(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {"N": {"type": "integer", "minimum": 5, "exclusiveMinimum": True}}
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["exclusiveMinimum"] == 5
    assert "minimum" not in schema


def test_exclusive_minimum_already_numeric_oas31_passthrough(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"schemas": {"N": {"type": "integer", "exclusiveMinimum": 5}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["exclusiveMinimum"] == 5


def test_exclusive_minimum_false_is_removed(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"schemas": {"N": {"type": "integer", "minimum": 5, "exclusiveMinimum": False}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert "exclusiveMinimum" not in schema
    assert schema["minimum"] == 5


def test_nullable_true_converts_string_type_to_array(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "paths": {},
        "components": {"schemas": {"N": {"type": "integer", "nullable": True}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["type"] == ["integer", "null"]
    assert "nullable" not in schema


def test_nullable_false_is_removed_without_touching_type(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "paths": {},
        "components": {"schemas": {"N": {"type": "integer", "nullable": False}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["type"] == "integer"
    assert "nullable" not in schema


def test_nullable_absent_leaves_schema_untouched(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"schemas": {"N": {"type": "integer"}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["type"] == "integer"
    assert "nullable" not in schema


def test_nullable_true_with_no_type_does_not_crash():
    from src.parser import _normalize_nullable
    schema = {"nullable": True}
    _normalize_nullable(schema)
    assert "nullable" not in schema
    assert "type" not in schema


def test_nullable_true_with_already_array_type_adds_null_once(tmp_path):
    doc = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"schemas": {"N": {"type": ["integer", "string"], "nullable": True}}},
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["N"]
    assert schema["type"] == ["integer", "string", "null"]


def test_response_body_with_nullable_field_passes_jsonschema_validation(tmp_path):
    """runner側のLevel4検証と同じ経路: nullable変換後のスキーマがjsonschemaでnull値を正しく許容すること。"""
    from jsonschema import Draft202012Validator

    doc = {
        "openapi": "3.0.3",
        "paths": {},
        "components": {
            "schemas": {
                "User": {
                    "type": "object",
                    "properties": {"age": {"type": "integer", "nullable": True}},
                }
            }
        },
    }
    api = parse_openapi(_write(tmp_path, doc))
    schema = api["components"]["schemas"]["User"]
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors({"age": None}))
    assert errors == []
