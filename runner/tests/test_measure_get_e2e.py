"""UI-generated GET/JSON mappings, real HTTP and real PostgreSQL, including faulty APIs.

Run with OTG_INTEGRATION_DB_CONFIG (a JSON psycopg2 configuration). Only a
uniquely named test table is created/deleted. The production GET checker is read-only.
"""
import copy
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2
import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[2]
SPEC = ROOT / "examples" / "measure-get-openapi.json"
API_PATH = "/v1/result/measure/get"


def test_measure_get_contract_and_ui_db_combinations(tmp_path):
    config_text = os.environ.get("OTG_INTEGRATION_DB_CONFIG")
    if not config_text:
        pytest.skip("OTG_INTEGRATION_DB_CONFIG is not set")
    config = json.loads(config_text)
    output = Path(os.environ.get("OTG_MEASURE_EVIDENCE_DIR", str(tmp_path / "evidence")))
    output.mkdir(parents=True, exist_ok=True)
    table = "otg_measure_" + uuid.uuid4().hex[:12]
    api = json.loads(SPEC.read_text(encoding="utf-8"))
    request_schema = copy.deepcopy(api["paths"][API_PATH]["get"]["requestBody"]["content"]["application/json"]["schema"])
    request_schema["anyOf"] = [{"required": ["site_id"]}, {"required": ["location_id"]}]
    request_schema["dependentRequired"] = {"start": ["end"], "end": ["start"]}
    validator = Draft202012Validator(request_schema, format_checker=FormatChecker())

    def sql(query, params=(), fetch=False):
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall() if fetch else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body, mode=""):
            data = b"not JSON" if mode == "invalid_json" else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain" if mode == "wrong_content_type" else "application/json")
            if status == 200 and mode != "missing_header":
                self.send_header("X-Result-Count", "invalid" if mode == "wrong_header" else str(len(body["result"])))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            server.calls += 1
            if self.headers.get("Authorization") != "Bearer measure-test-token":
                self.respond(401, {"error": "unauthorized"})
                return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            except (ValueError, json.JSONDecodeError):
                body = None
            if not validator.is_valid(body):
                self.respond(400, {"error": "invalid request"})
                return
            mode = self.path.removeprefix(API_PATH).strip("/")
            # Deliberately independent of the tool's SQL builder and predicate code.
            rows = sql(f'SELECT site_id, location_id, measured_at, item_name, measured_value FROM "{table}"', fetch=True)
            selected = []
            for site, location, when, item, value in rows:
                matches = []
                if "site_id" in body and mode != "ignore_site":
                    matches.append(site == body["site_id"])
                if "location_id" in body and mode != "ignore_location":
                    matches.append(location == body["location_id"])
                if matches and not (all(matches) if mode == "wrong_or" else any(matches)):
                    continue
                if "start" in body and mode != "ignore_start":
                    start = datetime.fromisoformat(body["start"].replace("Z", "+00:00"))
                    if when < start or (mode in {"exclude_start_boundary", "strict_correct"} and when == start):
                        continue
                if "end" in body and mode != "ignore_end":
                    end = datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
                    if when > end or (mode in {"exclude_end_boundary", "strict_correct"} and when == end):
                        continue
                if mode != "ignore_items" and item not in body["items"]:
                    continue
                if mode == "first_item_only" and body["items"] and item != body["items"][0]:
                    continue
                selected.append({"time": when.isoformat(), "item": item, "value": value})
            selected.reverse()  # Ordering is explicitly irrelevant.
            response = {"site_id": body.get("site_id", 2),
                        "start": body.get("start", "2026-01-01T00:00:00Z"),
                        "end": body.get("end", "2026-01-03T00:00:00Z"), "result": selected}
            if mode == "wrong_value" and selected:
                selected[0]["value"] += 1
            if mode == "wrong_root_type":
                response["site_id"] = "wrong"
            if mode == "missing_root_field":
                del response["start"]
            if mode == "wrong_root_datetime":
                response["start"] = "2026-02-30T00:00:00Z"
            if mode == "wrong_root_site_value":
                response["site_id"] += 100
            if mode == "wrong_root_start_value":
                response["start"] = "2026-01-01T00:00:01Z"
            if mode == "wrong_root_end_value":
                response["end"] = "2026-01-03T00:00:01Z"
            if mode == "equivalent_timezones":
                for key in ("start", "end"):
                    response[key] = datetime.fromisoformat(response[key].replace("Z", "+00:00")).astimezone(
                        timezone(timedelta(hours=9))
                    ).isoformat()
            self.respond(200, response, mode)

    sql(f'CREATE TABLE "{table}" (site_id integer, location_id text, measured_at timestamptz, '
        'item_name text, measured_value double precision)')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    environment = {**os.environ, "TEST_AUTH_TOKEN": "measure-test-token"}
    config_path = tmp_path / "db.json"
    config_path.write_text(json.dumps({"postgres": config}), encoding="utf-8")

    def command(args, input_text=None):
        return subprocess.run(args, cwd=ROOT, env=environment, input=input_text, capture_output=True, text=True, timeout=60)

    def bridge(name, args):
        process = command([sys.executable, "gui/tauri_bridge.py"], json.dumps({"command": name, "args": args}))
        assert process.returncode == 0, process.stdout + process.stderr
        response = json.loads(process.stdout)
        assert response["ok"], response
        return response["result"]

    def db_run(scenarios, mode="", evidence_name=None):
        spec = copy.deepcopy(api)
        spec["paths"] = {API_PATH + ("/" + mode if mode else ""): spec["paths"][API_PATH]}
        spec_path = tmp_path / "api.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        scenario_path = tmp_path / "scenarios.yaml"
        scenario_path.write_text(yaml.safe_dump({"scenarios": {"list": scenarios}}, allow_unicode=True), encoding="utf-8")
        evidence = output / ((evidence_name or mode or "correct") + ".json")
        process = command([sys.executable, "runner/db_scenario_runner.py", str(scenario_path), str(spec_path),
                           "--base-url", base_url, "--config", str(config_path), "--skip-health-check",
                           "--evidence-output", str(evidence)])
        assert evidence.exists(), process.stdout + process.stderr
        return process, json.loads(evidence.read_text(encoding="utf-8"))["cases"]

    try:
        for site, location in [(1, "A"), (2, "B"), (3, "C")]:
            for offset in range(-1, 4):
                when = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset)
                for index, item in enumerate(["temperature", "humidity", "pressure"]):
                    sql(f'INSERT INTO "{table}" VALUES (%s,%s,%s,%s,%s)',
                        (site, location, when, item, site * 10 + offset + index / 10))

        # Use the actual UI logic, with explicit human-supplied DB values and mappings.
        js = """
          import {buildDbScenarios} from './gui-tauri/src/db-scenario-editor.js';
          const operation = JSON.parse(process.argv[1]);
          const filter = (parameter, column, operator, group = null) => ({source: 'body', parameter, column, operator, group});
          const result = buildDbScenarios({operation, name: '測定結果', table: process.argv[2], expandCombinations: true,
            requestBody: {site_id: 1, location_id: 'B', start: '2026-01-01T00:00:00Z', end: '2026-01-03T00:00:00Z',
              items: ['temperature', 'humidity']}, responseStatus: 200, responseShape: 'array', responseArrayPath: 'result',
            readMappings: [{source: 'measured_at', target: 'time'}, {source: 'item_name', target: 'item'}, {source: 'measured_value', target: 'value'}],
            responseValues: [
              {path: 'site_id', mode: 'requestWithDefault', parameter: 'body:site_id', fixed: '2'},
              {path: 'start', mode: 'requestWithDefault', parameter: 'body:start', fixed: '"2026-01-01T00:00:00Z"'},
              {path: 'end', mode: 'requestWithDefault', parameter: 'body:end', fixed: '"2026-01-03T00:00:00Z"'}],
            readFilters: [filter('site_id', 'site_id', '=', 'A'), filter('location_id', 'location_id', '=', 'A'),
              filter('start', 'measured_at', '>='), filter('end', 'measured_at', '<='), filter('items', 'item_name', 'in')]});
          process.stdout.write(JSON.stringify(result));
        """
        operation = bridge("list_db_scenario_operations", {"path": str(SPEC)})[0]
        generated = command(["node", "--input-type=module", "-e", js, json.dumps(operation), table])
        assert generated.returncode == 0, generated.stderr
        scenarios = json.loads(generated.stdout)
        assert len(scenarios) == 18
        ui_scenarios = output / "ui-scenarios.yaml"
        bridge("save_db_scenario_yaml", {"path": str(ui_scenarios), "scenarios": scenarios})
        assert yaml.safe_load(ui_scenarios.read_text(encoding="utf-8"))["scenarios"]["list"] == scenarios
        from workflow.case_master import build_case_master, write_case_master
        from workflow.spec_writer import write_case_spec_excel
        master = build_case_master("測定結果API", None, ui_scenarios, SPEC)
        assert len(master["cases"]) == 18
        assert all(len(case["expected"]["response"]["values"]) == 3 for case in master["cases"])
        write_case_master(master, output / "db-case-master.json")
        write_case_spec_excel(master, output / "db-case-spec.xlsx")
        process, evidence = db_run(scenarios)
        assert process.returncode == 0, process.stdout + process.stderr
        assert len(evidence) == 18 and all(case["verdict"] == "OK" for case in evidence)
        assert all(case["response_contract"]["verdict"] == "OK" for case in evidence)
        assert all(len(case["response_value_checks"]) == 3 and
                   all(value["verdict"] == "OK" for value in case["response_value_checks"]) for case in evidence)
        assert any(item["boundary_present"] for case in evidence for item in case["db_response_comparison"]["filter_coverage"])
        process, evidence = db_run(scenarios, "equivalent_timezones")
        assert process.returncode == 0, process.stdout + process.stderr

        modes = ["ignore_site", "ignore_location", "ignore_start", "ignore_end", "ignore_items", "first_item_only",
                 "wrong_or", "exclude_start_boundary", "exclude_end_boundary", "wrong_value", "wrong_root_type",
                 "missing_root_field", "wrong_root_datetime", "missing_header", "wrong_header", "wrong_content_type", "invalid_json",
                 "wrong_root_site_value", "wrong_root_start_value", "wrong_root_end_value"]
        mutation_results = {}
        for mode in modes:
            process, evidence = db_run(scenarios, mode)
            assert process.returncode == 1, mode + "\n" + process.stdout + process.stderr
            assert any(case["verdict"] == "NG" for case in evidence), mode
            if mode in {"wrong_root_site_value", "wrong_root_start_value", "wrong_root_end_value"}:
                assert all(case["response_contract"]["verdict"] == "OK" for case in evidence), mode
                assert all(any(value["verdict"] == "NG" for value in case["response_value_checks"]) for case in evidence), mode
            mutation_results[mode] = sum(case["verdict"] == "NG" for case in evidence)

        # The human-configured operators, including exclusive endpoints, are the oracle.
        strict = copy.deepcopy(scenarios)
        for scenario in strict:
            for item in scenario["db_response_check"]["filters"]:
                if item["parameter"] == "start":
                    item["operator"] = ">"
                elif item["parameter"] == "end":
                    item["operator"] = "<"
        process, evidence = db_run(strict, "strict_correct")
        assert process.returncode == 0, process.stdout + process.stderr
        process, evidence = db_run(strict, evidence_name="wrong-inclusive-boundaries")
        assert process.returncode == 1 and any(case["verdict"] == "NG" for case in evidence)

        # Missing witnesses must not silently pass or make HTTP requests.
        sql(f'DELETE FROM "{table}" WHERE measured_at = %s', ("2026-01-01T00:00:00Z",))
        bounded = [case for case in scenarios if "start" in case["request"]["body"]]
        before = server.calls
        process, evidence = db_run(bounded, evidence_name="missing-boundary-data")
        assert process.returncode == 2, process.stdout + process.stderr
        assert server.calls == before
        assert all(case["verdict"] == "未確認" and "境界値" in case["detail"] for case in evidence)

        # Execute generated contract cases too, including isolated invalid dates and auth cases.
        generated = command([sys.executable, "src/cli.py", str(SPEC), "--output", str(output / "cases.json"),
                             "--excel-output", str(output / "test_spec.xlsx")])
        assert generated.returncode == 0, generated.stdout + generated.stderr
        executed = command([sys.executable, "runner/runner.py", str(output / "test_spec.xlsx"), str(SPEC),
                            "--base-url", base_url, "--skip-health-check", "--output", str(output / "result.xlsx")])
        (output / "contract-run.log").write_text(executed.stdout + executed.stderr, encoding="utf-8")
        assert executed.returncode == 0, executed.stdout + executed.stderr
        contract_count = len(json.loads((output / "cases.json").read_text(encoding="utf-8"))["cases"])
        summary = {"db_cases_passed": len(scenarios), "exclusive_boundary_cases_passed": len(strict),
                   "contract_cases_passed": contract_count, "faults_detected": mutation_results,
                   "response_value_checks_per_case": 3, "equivalent_timezone_cases_passed": len(scenarios),
                   "missing_boundary": "unverified without HTTP requests"}
        (output / "verification-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"18 UI-generated DB cases passed; {len(modes)} faulty API implementations detected; missing boundary unverified; contract cases passed.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        sql(f'DROP TABLE "{table}"')
