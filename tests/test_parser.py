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
