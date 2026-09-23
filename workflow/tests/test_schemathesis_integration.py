from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from workflow import cli


pytestmark = pytest.mark.skipif(
    shutil.which("schemathesis") is None,
    reason="Schemathesis 4.x is an optional local dependency",
)


class _HealthHandler(BaseHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        self.server.seen_methods.append(self.command)
        if code == 501:
            self.send_response(405)
            self.send_header("Allow", "GET")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        super().send_error(code, message, explain)

    def do_GET(self):
        self.server.seen_methods.append(self.command)
        authorization = self.headers.get("Authorization")
        self.server.seen_authorization.append(authorization)
        if self.path != "/health":
            self.send_error(404)
            return
        if self.server.require_auth and authorization != "Bearer integration-secret-token":
            payload = b'{"detail":"Unauthorized"}'
            status = 401
        else:
            payload = b'{"ok":true}'
            status = 200
        self.server.seen_statuses.append(status)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        self.server.seen_methods.append(self.command)
        if self.path != "/login":
            self.send_error(404)
            return
        payload = b'{"access_token":"integration-secret-token"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.mark.parametrize("save_cassette", [False, True])
@pytest.mark.parametrize("with_auth", [False, True])
def test_local_schemathesis_cli_creates_junit_and_html_without_external_target(tmp_path, capsys, save_cassette, with_auth):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    server.seen_methods = []
    server.seen_authorization = []
    server.seen_statuses = []
    server.require_auth = with_auth
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "loopback fixture", "version": "1"},
            "paths": {
                "/health": {
                    "get": {
                        "operationId": "healthCheck",
                        "responses": {
                            "200": {
                                "description": "healthy",
                                "content": {
                                    "application/json": {
                                        "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        }
        if with_auth:
            spec["components"] = {"securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            }}
            operation = spec["paths"]["/health"]["get"]
            operation["security"] = [{"BearerAuth": []}]
            operation["responses"]["401"] = {"description": "unauthorized"}
        (tmp_path / "openapi.json").write_text(json.dumps(spec), encoding="utf-8")
        project = tmp_path / "project.json"
        project.write_text(json.dumps({
            "schemaVersion": 1,
            "name": "loopback",
            "openapiPath": "openapi.json",
            "baseUrl": f"http://127.0.0.1:{server.server_port}",
            "outputDir": "artifacts",
            "selectedOperations": ["healthCheck"],
        }), encoding="utf-8")

        argv = ["run-schemathesis", "--project", str(project), "--max-examples", "1"]
        if save_cassette:
            argv.append("--save-cassette")
        auth_config_path = tmp_path / "auth.json"
        if with_auth:
            auth_config_path.write_text(json.dumps({
                "login_url": "/login",
                "method": "POST",
                "body": {"username": "tester", "password": "integration-password"},
            }), encoding="utf-8")
            argv.extend(["--auth-config", str(auth_config_path)])
        result = cli.main(argv)
        stdout_text = capsys.readouterr().out
        events = [json.loads(line) for line in stdout_text.splitlines()]
        artifacts = {event["kind"]: Path(event["path"]) for event in events if event.get("type") == "artifact"}

        assert result == 0, "\n".join(str(event.get("message")) for event in events)
        assert {"schemathesis_junit", "schemathesis_html", "schemathesis_manifest"} <= artifacts.keys()
        assert artifacts["schemathesis_junit"].is_file()
        report = artifacts["schemathesis_html"].read_text(encoding="utf-8")
        assert "GET /health" in report
        assert "成功 1" in report
        assert server.seen_methods
        assert set(server.seen_methods) == ({"GET", "POST"} if with_auth else {"GET"})
        if with_auth:
            assert "Bearer integration-secret-token" in server.seen_authorization
            assert None in server.seen_authorization
            assert any(
                value not in {None, "Bearer integration-secret-token"}
                for value in server.seen_authorization
            )
            assert 200 in server.seen_statuses
            assert 401 in server.seen_statuses
        else:
            assert set(server.seen_authorization) == {None}
        assert ("schemathesis_vcr" in artifacts) is save_cassette
        if save_cassette:
            assert artifacts["schemathesis_vcr"].is_file()
        if with_auth:
            assert "integration-secret-token" not in stdout_text
            for evidence in artifacts.values():
                assert "integration-secret-token" not in evidence.read_text(encoding="utf-8")
        assert not (tmp_path / "artifacts" / ".schemathesis").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
