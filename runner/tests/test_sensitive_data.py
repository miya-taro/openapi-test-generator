import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from response_validator import _strip_write_only
from sensitive_data import redact_sensitive_response


@pytest.mark.parametrize(
    ("body", "schema", "secret"),
    [
        (
            {"profile": {"credentialMaterial": "nested-private-value"}},
            {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "object",
                        "properties": {
                            "credentialMaterial": {"type": "string", "writeOnly": True},
                        },
                    },
                },
            },
            "nested-private-value",
        ),
        (
            {"items": [{"credentialMaterial": "array-private-value"}]},
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "credentialMaterial": {"type": "string", "writeOnly": True},
                            },
                        },
                    },
                },
            },
            "array-private-value",
        ),
        (
            {"tenants": {"tenant-a": {"credentialMaterial": "dynamic-private-value"}}},
            {
                "type": "object",
                "properties": {
                    "tenants": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "properties": {
                                "credentialMaterial": {"type": "string", "writeOnly": True},
                            },
                        },
                    },
                },
            },
            "dynamic-private-value",
        ),
        (
            {"credentialMaterial": "alternate-private-value"},
            {
                "_oneOfVariants": [
                    {"type": "object", "properties": {"publicName": {"type": "string"}}},
                    {
                        "type": "object",
                        "properties": {
                            "credentialMaterial": {"type": "string", "writeOnly": True},
                        },
                    },
                ],
            },
            "alternate-private-value",
        ),
    ],
)
def test_schema_write_only_values_are_redacted_at_every_response_depth(body, schema, secret):
    raw_body = json.dumps(body)

    redacted = redact_sensitive_response(raw_body, _strip_write_only(schema))

    assert secret not in redacted
    assert "[REDACTED]" in redacted
