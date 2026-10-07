import re

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.schema_example import NoSchemaExample, find_schema_example


def test_string_example_honors_pattern_and_length_limits():
    schema = {"type": "string", "pattern": "^[A-Z]{2}-[0-9]{3}$", "minLength": 6, "maxLength": 6}

    value = find_schema_example(schema)

    assert re.fullmatch(schema["pattern"], value)
    assert Draft202012Validator(schema).is_valid(value)


def test_email_example_fits_tight_maximum_length():
    schema = {"type": "string", "format": "email", "maxLength": 13}

    value = find_schema_example(schema)

    assert len(value) <= 13
    assert FormatChecker().check(value, "email") is None


def test_numeric_example_honors_bounds_and_multiple_of():
    schema = {"type": "integer", "minimum": 5, "maximum": 11, "multipleOf": 3}

    value = find_schema_example(schema)

    assert value == 6
    assert Draft202012Validator(schema).is_valid(value)


def test_array_example_honors_minimum_items_and_uniqueness():
    schema = {
        "type": "array",
        "minItems": 3,
        "maxItems": 3,
        "uniqueItems": True,
        "items": {"type": "string", "pattern": "^[a-z]+$"},
    }

    value = find_schema_example(schema)

    assert len(value) == 3
    assert len(set(value)) == 3
    assert Draft202012Validator(schema).is_valid(value)


def test_object_example_includes_required_nested_fields_and_omits_readonly():
    schema = {
        "type": "object",
        "required": ["name", "serverId", "address"],
        "properties": {
            "name": {"type": "string", "minLength": 2},
            "serverId": {"type": "integer", "readOnly": True},
            "address": {
                "type": "object",
                "required": ["zip"],
                "properties": {"zip": {"type": "string", "pattern": "^[0-9]{5}$"}},
            },
        },
    }

    value = find_schema_example(schema)

    assert value["name"]
    assert "serverId" not in value
    assert re.fullmatch(r"[0-9]{5}", value["address"]["zip"])
    assert Draft202012Validator({**schema, "required": ["name"]}).is_valid(value)


def test_enum_example_uses_value_that_meets_all_constraints():
    schema = {"type": "string", "enum": ["bad", "good"], "pattern": "^good$"}

    assert find_schema_example(schema) == "good"


def test_unsatisfiable_schema_has_no_generated_example():
    with pytest.raises(NoSchemaExample):
        find_schema_example({"type": "string", "minLength": 10, "maxLength": 2})
