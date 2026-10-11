"""Opt-in: generated error requests through runner CLI and real PostgreSQL snapshots."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_generated_errors_preserve_database(tmp_path):
    config_text = os.environ.get("OTG_INTEGRATION_DB_CONFIG")
    if not config_text:
        pytest.skip("OTG_INTEGRATION_DB_CONFIG is not set")
    config = json.loads(config_text)
    table = "otg_contract_" + uuid.uuid4().hex[:12]
    def sql(statement):
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement)
    sql(f'CREATE TABLE "{table}" (id serial primary key, value integer)')
    fault = "none"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def call(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if fault == "update":
                sql(f'UPDATE "{table}" SET value = value + 1')
            elif fault == "insert":
                sql(f'INSERT INTO "{table}" (value) VALUES (1)')
            elif fault == "delete":
                sql(f'DELETE FROM "{table}" WHERE id = (SELECT min(id) FROM "{table}")')
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"invalid input"}')
        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = call
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = Path(os.environ.get("OTG_CONTRACT_DB_EVIDENCE_DIR", tmp_path / "evidence"))
    output.mkdir(parents=True, exist_ok=True)
    try:
        paths = {"/check": {method: {"operationId": method, "parameters": [{"name": "id", "in": "query",
            "required": True, "schema": {"type": "integer", "minimum": 1}}], "responses": {
            "200": {"description": "OK"}, "400": {"description": "Invalid", "content": {"application/json": {"schema": {
                "type": "object", "required": ["error"], "properties": {"error": {"type": "string"}}}}}}},
            "x-otg-error-db-unchanged": [{"table": table, "columns": ["id", "value"], "where": {}}],
        } for method in ["get", "post", "put", "patch", "delete"]}}
        spec = tmp_path / "openapi.json"
        spec.write_text(json.dumps({"openapi": "3.1.0", "paths": paths}))
        db = tmp_path / "db.json"
        db.write_text(json.dumps({"postgres": config}))
        excel, cases = tmp_path / "cases.xlsx", tmp_path / "cases.json"
        subprocess.run([sys.executable, str(ROOT / "src/cli.py"), str(spec), "--no-normal", "-o", str(cases), "--excel-output", str(excel)], check=True, capture_output=True)
        count = len(json.loads(cases.read_text())["cases"])
        for fault in ("none", "update", "insert", "delete"):
            sql(f'TRUNCATE "{table}" RESTART IDENTITY')
            sql(f'INSERT INTO "{table}" (value) SELECT 1 FROM generate_series(1, {count + 1})')
            result = subprocess.run([sys.executable, str(ROOT / "runner/runner.py"), str(excel), str(spec),
                "--base-url", f"http://127.0.0.1:{server.server_port}", "--skip-health-check", "--config", str(db),
                "--output", str(output / f"{fault}.xlsx"), "--junit-xml", str(output / f"{fault}.xml")], capture_output=True, text=True)
            assert result.returncode == (0 if fault == "none" else 1), result.stdout + result.stderr
            evidence = json.loads((output / f"{fault}-db-evidence.json").read_text())
            assert len(evidence) == count
            assert all(row["scopes"][0]["verdict"] == ("OK" if fault == "none" else "NG") for row in evidence)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        sql(f'DROP TABLE "{table}"')
