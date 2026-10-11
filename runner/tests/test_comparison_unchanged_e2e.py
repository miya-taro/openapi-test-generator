"""Real HTTP + PostgreSQL: ordered inputs and error/read-only side effect detection."""
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg2
import pytest
import requests

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(0, str(ROOT))
from db_scenario import parse_scenarios, DBUnchangedCheck
from db_scenario_runner import _run_scenario, _safe_evidence
from db_backends import postgres_backend
from models import RunCase, RunResult
from request_builder import build_request_body
from response_schema import from_run_case
from verifier import verify
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.parser import parse_openapi


def test_order_rules_and_db_unchanged_against_faulty_http_apis(tmp_path):
    config_text = os.environ.get("OTG_INTEGRATION_DB_CONFIG")
    if not config_text:
        pytest.skip("OTG_INTEGRATION_DB_CONFIG is not set")
    config = json.loads(config_text)
    table = "otg_unchanged_" + uuid.uuid4().hex[:12]
    output = Path(os.environ.get("OTG_SIDE_EFFECT_EVIDENCE_DIR", str(tmp_path / "evidence")))
    output.mkdir(parents=True, exist_ok=True)

    def sql(statement, params=()):
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement, params)

    sql(f'CREATE TABLE "{table}" (id integer, site_id integer, name text, password text)')
    mode, calls = "none", []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def execute(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            calls.append((self.command, body))
            if self.path == "/ordered":
                valid = datetime.fromisoformat(body["start"].replace("Z", "+00:00")) <= datetime.fromisoformat(body["end"].replace("Z", "+00:00"))
                status = 200 if (valid or mode == "ignore_order") else 422
            else:
                if mode == "update":
                    sql(f'UPDATE "{table}" SET name = %s WHERE id = 1', ("changed",))
                elif mode == "insert":
                    sql(f'INSERT INTO "{table}" VALUES (3, 1, %s, %s)', ("extra", "secret"))
                elif mode == "delete":
                    sql(f'DELETE FROM "{table}" WHERE id = 1')
                elif mode == "grow":
                    sql(f'INSERT INTO "{table}" SELECT generate_series(10, 5010), 1, NULL, NULL')
                elif mode == "outside_scope":
                    sql(f'UPDATE "{table}" SET name = %s WHERE id = 2', ("changed",))
                status = 200 if self.command == "GET" else 422
            encoded = b'{"ok":true}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = execute

    responses = {str(status): {"description": "response", "content": {"application/json": {"schema": {
        "type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
    }}}} for status in [200, 422]}
    api = {"openapi": "3.1.0", "paths": {"/unchanged": {
        method.lower(): {"operationId": "check" + method, "responses": responses} for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]
    }, "/ordered": {"get": {"operationId": "ordered", "responses": responses, "requestBody": {
        "required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["start", "end"],
            "properties": {name: {"type": "string", "format": "date-time"} for name in ["start", "end"]},
            "x-otg-comparison-rules": [{"fields": ["start", "end"], "operator": "<=", "lower": "2026-01-01T00:00:00Z", "upper": "2026-01-02T00:00:00Z"}],
        }}}}}}}}
    api_path = output / "openapi.json"
    api_path.write_text(json.dumps(api), encoding="utf-8")
    api = parse_openapi(str(api_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    evidence_rows = []
    try:
        params, bodies = extract_specs(api)
        cases = [c for c in generate_test_cases(params, bodies, {"includeNormal": True, "includeAbnormal": True}) if c["keyword"] == "fieldComparison"]
        assert len(cases) == 3
        for mode in ["none", "ignore_order"]:
            verdicts = []
            for index, case in enumerate(cases):
                run = RunCase(f"TC-{index}", "ordered", "/ordered", "GET", "body", "requestBody", case["inputValue"], case["expectedStatus"], "", "", "", "")
                body = build_request_body(run, api).json_body
                response = requests.get(base_url + "/ordered", json=body, timeout=5)
                result = RunResult(run, response.status_code, response.text, dict(response.headers), 1, 0)
                verdict, detail = verify(result, from_run_case(run, api))
                verdicts.append(verdict)
                evidence_rows.append({"mode": mode, "request": body, "status": response.status_code, "verdict": verdict, "detail": detail})
            assert verdicts == (["OK", "OK", "OK"] if mode == "none" else ["OK", "OK", "NG"])

        # Generate the same no-change scenario shape as the UI uses, then execute it through the runner.
        script = '''import {buildDbScenario} from './gui-tauri/src/db-scenario-editor.js';
        console.log(JSON.stringify(buildDbScenario({operation:{operationId:'checkPOST',method:'POST'},name:'unchanged',
        table:process.argv[1],mode:'unchanged',unchangedColumns:'id, name, password',unchangedWhere:{site_id:1},
        unchangedStatus:422,requestBody:{value:'invalid'}})));'''
        generated = subprocess.run(["node", "--input-type=module", "-e", script, table], cwd=ROOT, text=True, capture_output=True, encoding="utf-8")
        assert generated.returncode == 0, generated.stderr
        raw = json.loads(generated.stdout)
        for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
            raw["request"]["operationId"] = "check" + method
            raw["response_check"]["expect"]["status"] = 200 if method == "GET" else 422
            scenario = parse_scenarios(json.dumps({"scenarios": [raw]}))[0]
            for mode in ["none", "update", "insert", "delete", "outside_scope"]:
                sql(f'DELETE FROM "{table}"')
                sql(f'INSERT INTO "{table}" VALUES (1, 1, %s, %s), (2, 2, %s, %s)', ("before", "secret", "outside", "other"))
                evidence = {"mode": mode, "method": method}
                with requests.Session() as session:
                    ok, detail, status, _, cleanup = _run_scenario(scenario, api, base_url, {"postgres": config}, {}, session, evidence=evidence)
                assert ok == (mode in ["none", "outside_scope"]), detail
                assert status == str(raw["response_check"]["expect"]["status"]) and cleanup == []
                snapshot = evidence["db_unchanged"][0]
                assert snapshot["before_count"] == 1
                if mode == "update":
                    assert snapshot["after_count"] == 1 and snapshot["verdict"] == "NG"
                safe = _safe_evidence(evidence)
                assert safe["db_unchanged"][0]["before_rows"][0]["password"] == "[REDACTED]"
                evidence_rows.append({**safe, "passed": ok, "detail": detail})

        # Empty tables are valid scopes: a later inserted row must still be detected.
        raw["request"]["operationId"] = "checkPOST"
        for mode in ["none", "insert"]:
            sql(f'DELETE FROM "{table}"')
            scenario = parse_scenarios(json.dumps({"scenarios": [raw]}))[0]
            evidence = {"mode": "empty_" + mode}
            with requests.Session() as session:
                result = _run_scenario(scenario, api, base_url, {"postgres": config}, {}, session, evidence=evidence)
            assert result[0] == (mode == "none")
            assert evidence["db_unchanged"][0]["before_count"] == 0
            evidence_rows.append(_safe_evidence(evidence))
        mode = "grow"
        with requests.Session() as session:
            evidence = {"mode": "exceeds_limit_after_http"}
            result = _run_scenario(scenario, api, base_url, {"postgres": config}, {}, session, evidence=evidence)
        assert result[0] is False and result[1].startswith("[UNVERIFIED]")
        assert evidence["db_unchanged"][0]["verdict"] == "未確認"
        evidence_rows.append(_safe_evidence(evidence))
        sql(f'DELETE FROM "{table}"')

        # Empty scopes, NULL selectors and injection-like values remain explicit and parameterized.
        assert postgres_backend.snapshot_rows(config, DBUnchangedCheck(table, ["id"], {"name": "' OR 1=1 --"})) == []
        sql(f'INSERT INTO "{table}" VALUES (4, NULL, NULL, NULL)')
        assert postgres_backend.snapshot_rows(config, DBUnchangedCheck(table, ["id"], {"site_id": None})) == [{"id": 4}]
        sql(f'INSERT INTO "{table}" SELECT generate_series(10, 5010), 1, NULL, NULL')
        scenario = parse_scenarios(json.dumps({"scenarios": [raw]}))[0]
        before_calls = len(calls)
        with requests.Session() as session:
            result = _run_scenario(scenario, api, base_url, {"postgres": config}, {}, session)
        assert result[0] is False and result[1].startswith("[UNVERIFIED]")
        assert len(calls) == before_calls
        (output / "evidence.json").write_text(json.dumps(evidence_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Order: 3 correct cases, 1 ignored-order defect detected. DB: 28 HTTP scenarios, 16 side-effect defects detected; scope/NULL/row limit verified.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        sql(f'DROP TABLE "{table}"')
