"""E2E tests: runner.py with pytest-httpserver."""
import sys
import shutil
import json
import subprocess
from pathlib import Path
import pytest
import openpyxl

RUNNER = Path(__file__).parent.parent / "runner.py"
FIXTURE = Path(__file__).parent / "fixtures" / "sample.xlsx"
OPENAPI = Path(__file__).parent / "fixtures" / "sample_openapi.json"

pytestmark = pytest.mark.skipif(
    shutil.which("curl.exe") is None,
    reason="curl.exe not found on PATH",
)

SAMPLE_OPENAPI = {
    "openapi": "3.0.0",
    "info": {"title": "Test", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "operationId": "getUsers",
                "parameters": [{"name": "page", "in": "query", "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createUser",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {"name": {"type": "string"}},
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            },
        }
    },
}


@pytest.fixture(autouse=True)
def write_openapi(tmp_path):
    p = tmp_path / "sample_openapi.json"
    p.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")
    return p


def run_runner(httpserver, excel_path, openapi_path, extra_args=None):
    base_url = httpserver.url_for("").rstrip("/")
    cmd = [
        sys.executable, str(RUNNER),
        str(excel_path), str(openapi_path),
        "--base-url", base_url,
    ]
    if extra_args:
        cmd += extra_args
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")


def test_dry_run_exits_0(httpserver, tmp_path, write_openapi):
    proc = run_runner(httpserver, FIXTURE, write_openapi, ["--dry-run"])
    assert proc.returncode == 0
    assert "DRY-RUN" in proc.stdout


def test_all_pass_exits_0(httpserver, tmp_path, write_openapi):
    # Register all 3 routes from sample.xlsx
    httpserver.expect_request("/users", query_string="page=1").respond_with_data(
        '{"items":[]}', content_type="application/json"
    )
    httpserver.expect_request("/users", query_string="page=0").respond_with_data(
        '{"error":"bad"}', status=400, content_type="application/json"
    )
    httpserver.expect_request("/users", method="POST").respond_with_data(
        '{"id":1}', status=201, content_type="application/json"
    )
    # health
    httpserver.expect_request("/health").respond_with_data("ok")

    out_path = tmp_path / "result.xlsx"
    proc = run_runner(
        httpserver, FIXTURE, write_openapi,
        ["--output", str(out_path), "--health-path", "/health"]
    )
    assert proc.returncode == 0
    assert out_path.exists()


def test_health_check_failure_exits_3(httpserver, tmp_path, write_openapi):
    # Don't register /health → connection refused on that path
    httpserver.expect_request("/health").respond_with_data("error", status=503)
    proc = run_runner(
        httpserver, FIXTURE, write_openapi,
        ["--health-path", "/health"]
    )
    assert proc.returncode == 3


def test_status_mismatch_exits_1(httpserver, tmp_path, write_openapi):
    # Return 500 for everything
    httpserver.expect_request("/health").respond_with_data("ok")
    httpserver.expect_request("/users").respond_with_data("error", status=500)
    out_path = tmp_path / "result.xlsx"
    proc = run_runner(
        httpserver, FIXTURE, write_openapi,
        ["--output", str(out_path), "--health-path", "/health"]
    )
    assert proc.returncode == 1
