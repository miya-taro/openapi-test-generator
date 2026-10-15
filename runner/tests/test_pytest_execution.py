"""Exercise the real pytest subprocess, HTTP requests, reports and isolation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(0, str(ROOT))

from execution_plan import contract_case, db_case
from workflow.case_master import build_case_master, write_case_master


API = {"openapi": "3.0.3", "info": {"title": "runtime", "version": "1"}, "paths": {
    "/login": {"post": {"operationId": "login", "requestBody": {"required": True, "content": {
        "application/json": {"schema": {"type": "object", "required": ["user"], "properties": {
            "user": {"type": "string", "example": "test"}}}}}},
        "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {
            "type": "object", "required": ["result"], "properties": {"result": {"type": "string"}}}}}}}}},
}}


def prepare(tmp_path, statuses=("200",), scenarios=None):
    api = tmp_path / "api.json"
    api.write_text(json.dumps(API), encoding="utf-8")
    cases = [{"id": f"TC-login-{i:03}", "operationId": "login", "summary": "正常なユーザー",
              "path": "/login", "method": "POST", "in": "body", "paramName": "requestBody",
              "inputValue": '{"user":"test"}', "expectedStatus": status, "expectedResponseTime": "3秒以内",
              "perspective": "正常系", "keyword": "type", "notes": ""} for i, status in enumerate(statuses, 1)]
    scenario_path = None
    if scenarios is not None:
        scenario_path = tmp_path / "scenarios.json"
        scenario_path.write_text(json.dumps({"scenarios": scenarios}), encoding="utf-8")
    master = build_case_master("runtime", None if scenarios is not None else {"cases": cases}, scenario_path, api)
    path = tmp_path / "case-master.json"
    write_case_master(master, path)
    (tmp_path / "db.json").write_text("{}", encoding="utf-8")
    return path, master


def run(tmp_path, httpserver, *, kind="contract", flags=(), env=None):
    command = [sys.executable, str(ROOT / "runner/pytest_runner.py"), str(tmp_path / "case-master.json"),
               "--kind", kind, "--base-url", httpserver.url_for("/"), "--skip-health-check",
               "--output", str(tmp_path / "result.xlsx"), "--junit-xml", str(tmp_path / "result.xml")]
    if kind == "db-scenario":
        command.extend(["--config", str(tmp_path / "db.json")])
    result = subprocess.run([*command, *flags], capture_output=True, text=True, encoding="utf-8",
                            cwd=ROOT, env=env, timeout=60)
    payload_path = tmp_path / "result.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8")) if payload_path.exists() else None
    return result, payload


@pytest.mark.parametrize("parallel", [1, 2])
def test_json_is_authority_and_each_case_is_a_pytest_item(tmp_path, httpserver, parallel):
    prepare(tmp_path, ("200", "400"))
    # The old executable spreadsheet and original specification are irrelevant to execution.
    (tmp_path / "test-spec.xlsx").write_bytes(b"not even an Excel file")
    (tmp_path / "api.json").unlink()
    httpserver.expect_request("/login", method="POST", json={"user": "test"}).respond_with_json({"result": "ok"})
    result, payload = run(tmp_path, httpserver, flags=("--parallel", str(parallel)))
    assert result.returncode == 1, result.stdout + result.stderr
    assert [case["status"] for case in payload["cases"]] == ["passed", "failed"]
    items = list(ET.parse(tmp_path / "result.xml").getroot().iter("testcase"))
    assert [item.attrib["name"] for item in sorted(items, key=lambda item: item.attrib["name"])] == ["TC-login-001", "TC-login-002"]
    assert len(httpserver.log) == 2
    assert (tmp_path / "result.xlsx").is_file()


def test_fail_fast_marks_unstarted_cases_and_never_reuses_old_results(tmp_path, httpserver):
    prepare(tmp_path, ("400", "200", "200"))
    httpserver.expect_request("/login").respond_with_json({"result": "ok"})
    (tmp_path / "result.xml").write_text('<testsuites><testsuite><testcase name="stale"/></testsuite></testsuites>', encoding="utf-8")
    result, payload = run(tmp_path, httpserver, flags=("--fail-fast",))
    assert result.returncode == 1, result.stdout + result.stderr
    assert [row["status"] for row in payload["cases"]] == ["failed", "not-run", "not-run"]
    assert len(httpserver.log) == 1
    xml = ET.parse(tmp_path / "result.xml").getroot()
    assert len(list(xml.iter("testcase"))) == 3
    assert len(list(xml.iter("skipped"))) == 2


def test_db_cases_execute_from_snapshot_with_no_original_yaml(tmp_path, httpserver):
    prepare(tmp_path, scenarios=[{"id": "login", "name": "ログイン", "request": {
        "operationId": "login", "body": {"user": "test"}}, "response_check": {"expect": {
            "status": 200, "body": {"result": "ok"}}}}])
    (tmp_path / "scenarios.json").unlink()
    httpserver.expect_request("/login", json={"user": "test"}).respond_with_json({"result": "ok"})
    result, payload = run(tmp_path, httpserver, kind="db-scenario")
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["cases"][0]["status"] == "passed"
    assert payload["cases"][0]["evidence"]["api_status"] == "200"


def test_tampered_plan_and_empty_selection_do_not_call_api(tmp_path, httpserver):
    path, master = prepare(tmp_path)
    master["execution"]["openapi"]["paths"] = {}
    path.write_text(json.dumps(master), encoding="utf-8")
    result, _ = run(tmp_path, httpserver)
    assert result.returncode == 3
    assert not httpserver.log
    prepare(tmp_path)
    result, _ = run(tmp_path, httpserver, flags=("--case-ids", "nonexistent"))
    assert result.returncode == 3
    assert not httpserver.log


def test_unrelated_pytest_configuration_cannot_select_or_run_other_tests(tmp_path, httpserver):
    prepare(tmp_path)
    httpserver.expect_request("/login").respond_with_json({"result": "ok"})
    env = dict(os.environ, PYTEST_ADDOPTS="--invalid-user-option", PYTEST_PLUGINS="nonexistent_plugin")
    result, payload = run(tmp_path, httpserver, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["cases"][0]["status"] == "passed"


def test_dry_run_has_no_side_effects(tmp_path, httpserver):
    prepare(tmp_path)
    result, payload = run(tmp_path, httpserver, flags=("--dry-run",))
    assert result.returncode == 0
    assert payload is None
    assert not httpserver.log


@pytest.mark.parametrize("value, expected", [(0, "0"), (False, "False"), ("", ""), (None, "")])
def test_plan_adapter_does_not_drop_zero_or_false(tmp_path, value, expected):
    _, master = prepare(tmp_path)
    case = master["cases"][0]
    case["definition"]["request"]["value"] = value
    assert contract_case(case).input_value == expected


def test_interrupted_started_request_is_not_reported_as_unstarted(tmp_path):
    import hashlib
    from pytest_runner import _complete_junit, _records
    _, master = prepare(tmp_path)
    case = master["cases"][0]
    records = tmp_path / "records"
    records.mkdir()
    path = records / (hashlib.sha256(case["caseId"].encode("utf-8")).hexdigest() + ".json")
    path.write_text(json.dumps({"caseId": case["caseId"], "definitionHash": case["definitionHash"],
                                "kind": case["kind"], "status": "running"}), encoding="utf-8")
    rows = _records([case], records)
    assert rows[0]["status"] == "error"
    assert "送信済みの可能性" in rows[0]["detail"]
    junit = tmp_path / "result.xml"
    _complete_junit(junit, [case], rows, [])
    root = ET.parse(junit).getroot()
    assert len(list(root.iter("error"))) == 1
    assert not list(root.iter("skipped"))


def test_login_setup_error_is_not_a_pass_and_does_not_leak_credentials(tmp_path, httpserver):
    prepare(tmp_path)
    auth = tmp_path / "auth.json"
    secret = "private-password-example"
    auth.write_text(json.dumps({"login_url": "/authenticate", "method": "POST", "body": {"password": secret},
                                "token_path": "id", "header_name": "auth-key"}), encoding="utf-8")
    httpserver.expect_request("/authenticate").respond_with_json({"error": secret}, status=401)
    result, payload = run(tmp_path, httpserver, flags=("--auth-config", str(auth)))
    assert result.returncode == 1, result.stdout + result.stderr
    assert payload["cases"][0]["status"] == "error"
    assert len(httpserver.log) == 1
    assert secret not in result.stdout + result.stderr
    assert secret not in (tmp_path / "result.json").read_text(encoding="utf-8")
    assert secret not in (tmp_path / "result.xml").read_text(encoding="utf-8")
    assert len(list(ET.parse(tmp_path / "result.xml").getroot().iter("error"))) == 1


def test_setup_failure_still_cleans_up_and_records_both_errors(tmp_path, httpserver, monkeypatch):
    import pytest_runner
    prepare(tmp_path)
    setup, teardown = tmp_path / "setup.sql", tmp_path / "teardown.sql"
    setup.write_text("SELECT 1", encoding="utf-8")
    teardown.write_text("SELECT 2", encoding="utf-8")
    calls = []
    def fail_hook(path, _config):
        calls.append(Path(path).name)
        raise RuntimeError("password=do-not-log-this")
    monkeypatch.setattr(pytest_runner, "_hook", fail_hook)
    code = pytest_runner.main([str(tmp_path / "case-master.json"), "--kind", "contract",
                               "--base-url", httpserver.url_for("/"), "--skip-health-check",
                               "--config", str(tmp_path / "db.json"), "--setup", str(setup), "--teardown", str(teardown),
                               "--output", str(tmp_path / "result.xlsx"), "--junit-xml", str(tmp_path / "result.xml")])
    assert code == 3
    assert calls == ["setup.sql", "teardown.sql"]
    payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert payload["cases"][0]["status"] == "not-run"
    assert len(payload["runErrors"]) == 2
    assert not httpserver.log
    assert "do-not-log-this" not in json.dumps(payload)
    from openpyxl import load_workbook
    book = load_workbook(tmp_path / "result.xlsx")
    assert book.active.title == "実行エラー"
    book.close()


def test_all_example_db_definitions_roundtrip_without_losing_checks(tmp_path):
    from db_scenario import load_scenarios
    import yaml
    files = [*ROOT.glob("examples/**/*.yaml"), *ROOT.glob("examples/**/*.yml"), *ROOT.glob("examples/**/*.json")]
    count = 0
    for path in files:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or "scenarios" not in document:
            continue
        scenarios = load_scenarios(path)
        for scenario in scenarios:
            definition = scenario.case_definition()
            case = {"caseId": scenario.case_id, "title": scenario.name, "definition": copy.deepcopy(definition)}
            restored = db_case(case)
            assert restored.case_definition() == definition, (str(path), scenario.name)
            assert restored.case_id == scenario.case_id
            count += 1
    assert count >= 10


def test_generated_contract_matrix_uses_pytest_and_detects_fault(tmp_path, monkeypatch):
    import threading
    from docs.release_candidate_api import CandidateServer, TOKEN
    from src.parser import parse_openapi
    from src.extractor import extract_specs, extract_auth_specs
    from src.generator import generate_test_cases
    from src.id_assigner import assign_ids

    spec = ROOT / "docs/release_candidate_openapi.json"
    api = parse_openapi(str(spec))
    params, bodies = extract_specs(api)
    cases = assign_ids(generate_test_cases(params, bodies, {
        "includeNormal": True, "includeAbnormal": True, "enumFullCoverage": True,
    }, extract_auth_specs(api)))
    server = CandidateServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TEST_AUTH_TOKEN", TOKEN)
    monkeypatch.delenv("TEST_AUTH_HEADER_NAME", raising=False)
    monkeypatch.delenv("TEST_AUTH_HEADER_VALUE", raising=False)
    try:
        master = build_case_master("matrix", {"cases": cases}, None, spec)
        path = tmp_path / "case-master.json"
        write_case_master(master, path)
        command = [sys.executable, str(ROOT / "runner/pytest_runner.py"), str(path), "--kind", "contract",
                   "--base-url", f"http://127.0.0.1:{server.server_port}", "--skip-health-check",
                   "--output", str(tmp_path / "result.xlsx"), "--junit-xml", str(tmp_path / "result.xml")]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
        assert len(payload["cases"]) == len(cases) >= 150
        assert all(row["status"] == "passed" for row in payload["cases"])
        assert {row["request"]["method"] for row in payload["cases"]} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
        assert TOKEN not in json.dumps(payload)
        server.fault = "wrong_type"
        selected = next(case["id"] for case in cases if case["operationId"] == "catalog" and case["in"] == "operation")
        failure = subprocess.run([*command, "--case-ids", selected], capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert failure.returncode == 1, failure.stdout + failure.stderr
        assert json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))["cases"][0]["status"] == "failed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
