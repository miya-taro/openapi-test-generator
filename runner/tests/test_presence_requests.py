"""Field-level tests must isolate their target from conditional presence rules."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2]))
from models import RunCase
from request_builder import build_request_body
from src.parser import parse_openapi
from src.presence import complete_presence

SPEC = Path(__file__).parents[2] / "examples" / "measure-get-openapi.json"


def body_for(name, value, status="200", example=None):
    api = parse_openapi(str(SPEC))
    schema = api["paths"]["/v1/result/measure/get"]["get"]["requestBody"]["content"]["application/json"]["schema"]
    if example is not None:
        schema["example"] = example
    case = RunCase("TC-1", "getMeasureResults", "/v1/result/measure/get", "GET", "body", name,
                   value, status, "", "", "", "")
    return build_request_body(case, api).json_body


@pytest.mark.parametrize("name,mate", [("start", "end"), ("end", "start")])
@pytest.mark.parametrize("value,status", [("2026-01-01T00:00:00Z", "200"), ("invalid-date", "4xx"), ("null", "4xx")])
def test_datetime_case_includes_companion_without_changing_target(name, mate, value, status):
    body = body_for(name, value, status)
    assert mate in body
    assert body[name] == (None if value == "null" else value)
    assert "site_id" in body and "items" in body


@pytest.mark.parametrize("name", ["start", "end"])
def test_omitting_optional_date_omits_its_companion(name):
    body = body_for(name, "（省略）", example={"items": ["x"], "site_id": 1,
                                            "start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"})
    assert "start" not in body and "end" not in body


def test_omitting_site_keeps_location_for_normal_field_case():
    body = body_for("site_id", "（省略）")
    assert "site_id" not in body and "location_id" in body


def test_negative_field_case_does_not_violate_other_presence_rule():
    body = body_for("items", json.dumps([1]), "4xx")
    assert body["items"] == [1]
    assert "site_id" in body


@pytest.mark.parametrize("marker,fields", [
    ("0:neither", set()), ("0:first", {"site_id"}), ("0:second", {"location_id"}),
    ("0:both", {"site_id", "location_id"}), ("1:first", {"start"}), ("1:second", {"end"}),
    ("1:neither", set()), ("1:both", {"start", "end"}),
])
def test_presence_cases_preserve_intentional_invalid_combinations(marker, fields):
    body = body_for("requestBody", "__PRESENCE_RULE__" + marker)
    tested = {"site_id", "location_id"} if marker.startswith("0:") else {"start", "end"}
    assert set(body) & tested == fields
    assert "items" in body


def test_overlapping_rules_use_an_alternative_outside_the_omitted_group():
    schema = {"properties": {name: {"type": "integer"} for name in ("a", "b", "c")},
              "x-otg-presence-rules": [{"kind": "atLeastOne", "fields": ["a", "b"]},
                                       {"kind": "together", "fields": ["a", "c"]}]}
    body = complete_presence({"a": 1}, schema, lambda _schema: 1, target="c")
    assert body == {"b": 1}


def test_transitive_companions_preserve_the_invalid_target_value():
    schema = {"properties": {name: {"type": "integer"} for name in ("a", "b", "c")},
              "x-otg-presence-rules": [{"kind": "together", "fields": ["a", "b"]},
                                       {"kind": "together", "fields": ["b", "c"]}]}
    body = complete_presence({"c": "invalid"}, schema, lambda _schema: 1, target="c")
    assert body == {"a": 1, "b": 1, "c": "invalid"}
