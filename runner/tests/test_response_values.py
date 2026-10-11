"""Explicit response expectations using the actual request sent to the API."""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_scenario import ResponseCheck, ScenarioError, parse_scenarios
from response_check import check


@pytest.mark.parametrize("source", ["body", "path", "query"])
def test_uses_current_request_and_requires_same_value(source):
    rule = {"path": "data.site_id", "source": source, "parameter": "site_id"}
    response_check = ResponseCheck(expect_values=[rule])
    request = {source: {"site_id": 7}}
    evidence = []
    assert check(response_check, 200, {"data": {"site_id": 7}}, request, evidence)[0]
    assert evidence[0]["expected"] == 7 and evidence[0]["verdict"] == "OK"
    assert not check(response_check, 200, {"data": {"site_id": 8}}, request)[0]


@pytest.mark.parametrize("actual,expected,ok", [
    (1, 1.0, True), (True, 1, False), (1, True, False), ("1", 1, False),
    ({"a": True}, {"a": 1}, False), ([True], [1], False),
    ({"a": 1}, {"a": 1}, True), (None, None, True),
])
def test_fixed_values_use_json_value_types(actual, expected, ok):
    response_check = ResponseCheck(expect_values=[{"path": "value", "source": "fixed", "value": expected}])
    assert check(response_check, 200, {"value": actual})[0] is ok


@pytest.mark.parametrize("actual,expected,ok", [
    ("2026-01-01T09:00:00+09:00", "2026-01-01T00:00:00Z", True),
    ("2026-01-01t00:00:00z", "2026-01-01T00:00:00.000Z", True),
    ("2026-01-01T00:00:01Z", "2026-01-01T00:00:00Z", False),
    ("2026-02-30T00:00:00Z", "2026-02-30T00:00:00Z", False),
    ("2026-01-01T00:00:00", "2026-01-01T00:00:00", False),
    (None, None, False),
    ("2026-01-01T00:00:00.0000001Z", "2026-01-01T00:00:00.0000002Z", False),
    ("2026-01-01T00:00:00.00000010Z", "2026-01-01T09:00:00.0000001+09:00", True),
])
def test_datetime_compares_instants_and_rejects_invalid_format(actual, expected, ok):
    response_check = ResponseCheck(expect_values=[{
        "path": "start", "source": "body", "parameter": "start", "comparison": "date-time",
    }])
    assert check(response_check, 200, {"start": actual}, {"body": {"start": expected}})[0] is ok


def test_missing_input_is_not_silently_skipped():
    rule = {"path": "start", "source": "body", "parameter": "start"}
    assert not check(ResponseCheck(expect_values=[rule]), 200, {"start": "x"}, {"body": {}})[0]
    evidence = []
    assert check(ResponseCheck(expect_values=[{**rule, "when_missing": "skip"}]),
                 200, {"start": "x"}, {"body": {}}, evidence)[0]
    assert evidence[0]["verdict"] == "対象外"
    assert not check(ResponseCheck(expect_values=[{**rule, "when_missing": "skip"}]),
                     200, {}, {"body": {"start": "x"}})[0]


def test_explicit_fallback_is_checked_only_when_input_is_missing():
    rule = {"path": "id", "source": "body", "parameter": "id", "when_missing": "fixed", "value": 2}
    response_check = ResponseCheck(expect_values=[rule])
    assert check(response_check, 200, {"id": 2}, {"body": {}})[0]
    assert not check(response_check, 200, {"id": 3}, {"body": {}})[0]
    assert check(response_check, 200, {"id": 1}, {"body": {"id": 1}})[0]
    assert not check(response_check, 200, {"id": 2}, {"body": {"id": 1}})[0]


def test_no_values_are_exposed_in_failure_detail():
    rule = {"path": "token", "source": "fixed", "value": "private"}
    ok, detail = check(ResponseCheck(expect_values=[rule]), 200, {"token": "other-private"})
    assert not ok and "private" not in detail


def parsed(values):
    text = yaml.safe_dump({"scenarios": [{"name": "values", "request": {"operationId": "get"},
                                         "response_check": {"expect": {"values": values}}}]})
    return parse_scenarios(text)[0]


def test_value_definitions_persist_in_case_id_and_definition():
    scenario = parsed([{"path": "site_id", "source": "body", "parameter": "site_id"}])
    assert scenario.case_definition()["responseCheck"]["expectedValues"][0]["parameter"] == "site_id"
    other = parsed([{"path": "site_id", "source": "fixed", "value": 1}])
    assert scenario.case_id != other.case_id


@pytest.mark.parametrize("values", [
    None, {}, [None], [{"source": "fixed", "value": 1}],
    [{"path": "id", "source": "fixed"}], [{"path": "id", "source": []}],
    [{"path": "id", "source": "body"}],
    [{"path": "id", "source": "body", "parameter": "id", "when_missing": "guess"}],
    [{"path": "id", "source": "fixed", "value": 1, "comparison": []}],
    [{"path": "id", "source": "fixed", "value": 1}] * 2,
    [{"path": "id", "source": "body", "parameter": "id", "when_missing": "fixed"}],
])
def test_invalid_definitions_are_rejected(values):
    with pytest.raises(ScenarioError):
        parsed(values)


def test_runner_records_and_masks_value_evidence(monkeypatch, tmp_path):
    import db_scenario_runner as runner
    api = {"openapi": "3.1.0", "paths": {"/get": {"get": {"operationId": "get", "responses": {
        "200": {"description": "OK", "content": {"application/json": {"schema": {
            "type": "object", "properties": {"secret_note": {"type": "string", "writeOnly": True},
                                               "id": {"type": "integer"}},
        }}}},
    }}}}}
    scenario = {"scenarios": [{"name": "masked", "request": {"operationId": "get", "body": {"id": 5}},
                                "response_check": {"expect": {"status": 200, "values": [
                                    {"path": "secret_note", "source": "fixed", "value": "private-value"},
                                    {"path": "id", "source": "body", "parameter": "id"},
                                ]}}}]}
    spec, scenarios, config, evidence = [tmp_path / name for name in ("api.json", "scenarios.yaml", "db.json", "evidence.json")]
    spec.write_text(json.dumps(api), encoding="utf-8")
    scenarios.write_text(yaml.safe_dump(scenario), encoding="utf-8")
    config.write_text("{}", encoding="utf-8")
    response = {"secret_note": "private-value", "id": 5}
    monkeypatch.setattr(runner, "_call_api", lambda *args, **kwargs: runner.APIResponse(
        200, response, None, json.dumps(response), {"Content-Type": "application/json"}, 0,
    ))
    monkeypatch.setattr(sys, "argv", ["runner", str(scenarios), str(spec), "--base-url", "http://x",
                                     "--config", str(config), "--skip-health-check", "--evidence-output", str(evidence)])
    assert runner.main() == 1  # A returned writeOnly field must also fail the shared contract check.
    payload = evidence.read_text(encoding="utf-8")
    assert "private-value" not in payload
    checks = json.loads(payload)["cases"][0]["response_value_checks"]
    assert checks[0]["expected"] == checks[0]["actual"] == "[REDACTED]"
    assert checks[1]["expected"] == checks[1]["actual"] == 5
