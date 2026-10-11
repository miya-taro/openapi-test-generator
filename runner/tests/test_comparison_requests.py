"""Cross-field cases must preserve their target and isolate other constraints."""
import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

sys.path.insert(0, str(Path(__file__).parents[1]))
sys.path.insert(0, str(Path(__file__).parents[2]))
from models import RunCase
from request_builder import build_request_body
from src.comparison_rules import KEY, comparable, complete_comparisons, matches, validate_rules
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.parser import parse_openapi, OpenAPIParseError

SPEC = Path(__file__).parents[2] / "examples" / "measure-get-openapi.json"
PATH = "/v1/result/measure/get"
RULE = {"fields": ["start", "end"], "operator": "<=", "lower": "2026-01-01T00:00:00Z", "upper": "2026-01-03T00:00:00Z"}


def api_with_rule(tmp_path, rule=None):
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    raw["paths"][PATH]["get"]["requestBody"]["content"]["application/json"]["schema"][KEY] = [rule or copy.deepcopy(RULE)]
    file = tmp_path / "comparison.json"
    file.write_text(json.dumps(raw), encoding="utf-8")
    api = parse_openapi(str(file))
    return api, api["paths"][PATH]["get"]["requestBody"]["content"]["application/json"]["schema"]


def case_body(api, name, value, status="200"):
    case = RunCase("TC-1", "getMeasureResults", PATH, "GET", "body", name, value, status, "", "", "", "")
    return build_request_body(case, api).json_body


@pytest.mark.parametrize("operator,expected", [("<=", [True, True, False]), ("<", [True, False, False]),
                                               (">=", [False, True, True]), (">", [False, False, True])])
def test_generated_order_variants_are_individually_schema_valid(tmp_path, operator, expected):
    api, schema = api_with_rule(tmp_path, {**RULE, "operator": operator})
    params, bodies = extract_specs(api)
    opts = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
    cases = [c for c in generate_test_cases(params, bodies, opts) if c["keyword"] == "fieldComparison"]
    assert len(cases) == 3
    for case, valid in zip(cases, expected, strict=True):
        body = case_body(api, case["paramName"], case["inputValue"], case["expectedStatus"])
        assert Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(body)
        assert matches(body, schema, schema[KEY][0]) is valid
        assert case["expectedStatus"] == ("2xx" if valid else "4xx")
    normal = [c for c in generate_test_cases(params, bodies, {**opts, "includeAbnormal": False}) if c["keyword"] == "fieldComparison"]
    assert len(normal) == sum(expected)


@pytest.mark.parametrize("target,value", [("start", "2099-01-01T00:00:00Z"), ("end", "1900-01-01T00:00:00Z")])
def test_field_case_keeps_target_and_repairs_companion(tmp_path, target, value):
    api, schema = api_with_rule(tmp_path)
    body = case_body(api, target, value)
    assert body[target] == value
    assert matches(body, schema, RULE)


def test_invalid_datetime_is_sent_unchanged_and_optional_pair_can_be_omitted(tmp_path):
    api, _ = api_with_rule(tmp_path)
    body = case_body(api, "start", "invalid-time", "4xx")
    assert body["start"] == "invalid-time" and "end" in body
    body = case_body(api, "start", "（省略）")
    assert "start" not in body and "end" not in body


def test_precision_and_timezone_are_compared_as_instants():
    schema = {"type": "string", "format": "date-time"}
    assert comparable("2026-01-01T09:00:00.1234567+09:00", schema) == comparable("2026-01-01T00:00:00.123456700Z", schema)
    assert comparable("2026-01-01T00:00:00.1234567Z", schema) < comparable("2026-01-01T00:00:00.1234568Z", schema)


def test_numeric_strict_boundary_fails_explicitly_when_companion_is_impossible():
    schema = {"properties": {k: {"type": "integer", "minimum": 0, "maximum": 10} for k in ["low", "high"]},
              KEY: [{"fields": ["low", "high"], "operator": "<", "lower": 0, "upper": 10}]}
    validate_rules(schema)
    assert complete_comparisons({"low": 5, "high": 3}, schema, target="low")["low"] == 5
    with pytest.raises(ValueError, match="生成できません"):
        complete_comparisons({"low": 10, "high": 5}, schema, target="low")


@pytest.mark.parametrize("change", [{"operator": []}, {"lower": "invalid"}, {"upper": RULE["lower"]}, {"fields": ["start", "start"]}])
def test_bad_rules_rejected_before_generation(tmp_path, change):
    with pytest.raises(OpenAPIParseError):
        api_with_rule(tmp_path, {**RULE, **change})


def test_baseline_can_adjust_either_side_of_strict_numeric_rule():
    schema = {"properties": {k: {"type": "integer", "minimum": 0, "maximum": 10} for k in ["low", "high"]},
              KEY: [{"fields": ["low", "high"], "operator": "<", "lower": 0, "upper": 10}]}
    body = complete_comparisons({"low": 0, "high": 0}, schema)
    assert body["low"] < body["high"]


def test_unsatisfiable_generated_request_is_reported_without_http_send(monkeypatch, tmp_path):
    import http_client
    from models import EXIT_ERROR
    api, schema = api_with_rule(tmp_path)
    schema["properties"] = {k: {"type": "integer", "minimum": 0, "maximum": 10} for k in ["start", "end"]}
    schema["required"] = ["start", "end"]
    schema.pop("x-otg-presence-rules", None)
    schema[KEY] = [{"fields": ["start", "end"], "operator": "<", "lower": 0, "upper": 10}]
    monkeypatch.setattr(http_client, "_send_request", lambda *_args: pytest.fail("must not send an invalid normal case"))
    case = RunCase("TC-1", "getMeasureResults", PATH, "GET", "body", "start", "10", "2xx", "", "", "", "")
    result = http_client.execute_with_openapi(case, "http://localhost", api)
    assert result.exit_code == EXIT_ERROR and "生成できません" in result.error


def test_normalization_precedes_numeric_rule_validation(tmp_path):
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    schema = raw["paths"][PATH]["get"]["requestBody"]["content"]["application/json"]["schema"]
    schema["properties"].update({k: {"type": "integer", "minimum": 0, "exclusiveMinimum": True} for k in ["low", "high"]})
    schema[KEY] = [{"fields": ["low", "high"], "operator": "<=", "lower": 1, "upper": 2}]
    file = tmp_path / "numeric.json"
    file.write_text(json.dumps(raw), encoding="utf-8")
    assert parse_openapi(str(file))


def test_nested_rule_is_rejected_instead_of_silently_not_generating_cases(tmp_path):
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    schema = raw["paths"][PATH]["get"]["requestBody"]["content"]["application/json"]["schema"]
    schema["properties"]["nested"] = {"type": "object", "properties": {name: {"type": "string", "format": "date-time"} for name in ["start", "end"]}, KEY: [RULE]}
    file = tmp_path / "nested.json"
    file.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(OpenAPIParseError, match="直下"):
        parse_openapi(str(file))
