import json

import pytest

from src.parser import parse_openapi
from src.schema_example import find_schema_example, NoSchemaExample
from response_validator import resolve_response_schema, validate_body


def parsed_schema(tmp_path, schema):
    path = tmp_path / "api.json"
    path.write_text(json.dumps({"openapi": "3.1.0", "paths": {"/test": {"get": {
        "operationId": "test", "responses": {"200": {"content": {"application/json": {"schema": schema}}}},
    }}}}), encoding="utf-8")
    api = parse_openapi(str(path))
    return api, resolve_response_schema("test", "/test", "GET", "200", api)


@pytest.mark.parametrize("schema,valid,invalid", [
    ({"allOf": [{"type": "integer", "minimum": 2}, {"maximum": 4}]}, 3, 5),
    ({"allOf": [{"type": "object", "properties": {"n": {"minimum": 2}}},
                {"properties": {"n": {"type": "integer", "maximum": 4}}, "required": ["n"]}]}, {"n": 3}, {"n": 5}),
    ({"oneOf": [{"type": "integer"}, {"type": "number", "minimum": 0}]}, -1, 1),
    ({"type": "object", "properties": {"n": {"oneOf": [{"type": "integer"}, {"minimum": 0}]}}, "required": ["n"]}, {"n": -1}, {"n": 1}),
    ({"type": "array", "items": {"oneOf": [{"type": "integer"}, {"type": "number"}]}}, [1.5], [1]),
    ({"anyOf": [{"type": "integer"}, {"type": "number"}], "maximum": 3}, 1, 4),
    ({"allOf": [{"type": "object", "properties": {"a": {}}, "additionalProperties": False},
                {"properties": {"b": {}}}]}, {"a": 1}, {"a": 1, "b": 2}),
])
def test_preserves_composition_semantics(tmp_path, schema, valid, invalid):
    _, resolved = parsed_schema(tmp_path, schema)
    assert validate_body(json.dumps(valid), resolved) == []
    assert validate_body(json.dumps(invalid), resolved)


def test_generation_never_uses_invalid_composed_sample(tmp_path):
    api, _ = parsed_schema(tmp_path, {"allOf": [{"type": "integer", "minimum": 2}, {"maximum": 4}]})
    schema = api["paths"]["/test"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert 2 <= find_schema_example(schema) <= 4
    api, _ = parsed_schema(tmp_path, {"oneOf": [{"type": "integer"}, {"type": "integer"}]})
    schema = api["paths"]["/test"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    with pytest.raises(NoSchemaExample):
        find_schema_example(schema)


def test_write_only_inside_combinator(tmp_path):
    _, schema = parsed_schema(tmp_path, {"allOf": [{"type": "object", "required": ["password"],
        "properties": {"password": {"type": "string", "writeOnly": True}}}]})
    assert validate_body("{}", schema) == []
    assert validate_body('{"password":"secret"}', schema)
