"""Integration tests using pytest-httpserver (real HTTP requests via requests library)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from http_client import execute_with_openapi
from models import EXIT_OK, RunCase


def make_case(**kwargs) -> RunCase:
    defaults = dict(
        id="TC-INT-001",
        operation_id="getItems",
        path="/items",
        method="GET",
        param_in="query",
        param_name="page",
        input_value="1",
        expected_status="200",
        expected_response_body="",
        expected_response_header="",
        expected_response_time="3秒以内",
        expected_result="",
    )
    defaults.update(kwargs)
    return RunCase(**defaults)


def test_get_200(httpserver):
    httpserver.expect_request("/items", query_string="page=1").respond_with_data(
        '{"items":[]}', content_type="application/json"
    )
    case = make_case()
    result = execute_with_openapi(case, httpserver.url_for("").rstrip("/"), None)
    assert result.actual_status == 200
    assert result.exit_code == EXIT_OK


def test_get_404(httpserver):
    httpserver.expect_request("/items").respond_with_data(
        '{"error":"not found"}', status=404, content_type="application/json"
    )
    case = make_case(input_value="（省略）")
    result = execute_with_openapi(case, httpserver.url_for("").rstrip("/"), None)
    assert result.actual_status == 404


def test_elapsed_ms_positive(httpserver):
    httpserver.expect_request("/items", query_string="page=1").respond_with_data("ok")
    case = make_case()
    result = execute_with_openapi(case, httpserver.url_for("").rstrip("/"), None)
    assert result.elapsed_ms > 0
