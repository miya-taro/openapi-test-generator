import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from http_client import execute_with_openapi, health_check, check_curl_available
from models import RunCase, RunResult


def make_case(**kwargs) -> RunCase:
    defaults = dict(
        id="TC-001-001",
        operation_id="getUsers",
        path="/users",
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


HEADER_BLOCK = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
HEADER_BLOCK_400 = "HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\n\r\n"


def mock_curl(body_and_metrics: str, returncode: int = 0, header_block: str = HEADER_BLOCK):
    m = MagicMock()
    m.stdout = header_block + body_and_metrics
    m.stderr = ""
    m.returncode = returncode
    return m


# --- stdout parsing tests ---

def test_parse_200_response():
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"items":[]}\n200\n0.123')
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_status == 200
    assert result.elapsed_ms == pytest.approx(123.0)
    assert result.actual_body == '{"items":[]}'
    assert result.curl_exit_code == 0
    assert result.error is None


def test_parse_400_response():
    case = make_case(input_value="0")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"error":"bad request"}\n400\n0.050', header_block=HEADER_BLOCK_400)
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_status == 400
    assert result.elapsed_ms == pytest.approx(50.0)


def test_response_headers_parsed():
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('ok\n200\n0.010')
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_headers.get("Content-Type") == "application/json"


def test_curl_command_stored():
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('ok\n200\n0.010')
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.curl_command.startswith("curl.exe")
    assert "http://localhost:8080/users" in result.curl_command


def test_curl_timeout_returns_error():
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl("", returncode=28, header_block="")
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.curl_exit_code == 28
    assert result.actual_status == 0
    assert result.error is not None


def test_curl_not_found_returns_error():
    case = make_case()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.curl_exit_code == 127
    assert "not found" in result.error


HEADER_201 = "HTTP/1.1 201 Created\r\nContent-Type: application/json\r\n\r\n"


def test_auth_token_added_when_env_set(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_TOKEN", "mytoken")
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('ok\n200\n0.010')
        execute_with_openapi(case, "http://localhost:8080", None)
        cmd = mock_run.call_args[0][0]
    assert "Authorization: Bearer mytoken" in " ".join(cmd)


def test_no_auth_header_without_token(monkeypatch):
    monkeypatch.delenv("TEST_AUTH_TOKEN", raising=False)
    case = make_case()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('ok\n200\n0.010')
        execute_with_openapi(case, "http://localhost:8080", None)
        cmd = mock_run.call_args[0][0]
    assert "Authorization" not in " ".join(cmd)


def test_body_param_adds_content_type():
    case = make_case(
        method="POST", param_in="body", param_name="name", input_value="Alice"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"id":1}\n201\n0.030', header_block=HEADER_201)
        execute_with_openapi(case, "http://localhost:8080", None)
        cmd = mock_run.call_args[0][0]
    assert any("Content-Type: application/json" in a for a in cmd)


def test_body_in_curl_args():
    case = make_case(
        method="POST", param_in="body", param_name="name", input_value="Alice"
    )
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"id":1}\n201\n0.030', header_block=HEADER_201)
        execute_with_openapi(case, "http://localhost:8080", None)
        cmd = mock_run.call_args[0][0]
    assert "-d" in cmd


# --- health_check tests ---

def _mock_health(code: str, returncode: int = 0):
    m = MagicMock()
    m.stdout = code
    m.stderr = ""
    m.returncode = returncode
    return m


def test_health_check_success():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_health("200")
        assert health_check("http://localhost:8080") is True


def test_health_check_failure_5xx():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_health("503")
        assert health_check("http://localhost:8080") is False


def test_health_check_curl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert health_check("http://localhost:8080") is False


# --- check_curl_available tests ---

def test_check_curl_available_raises_when_not_found():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="curl.exe が見つかりません"):
            check_curl_available()


def test_check_curl_available_ok_when_found():
    with patch("shutil.which", return_value="/usr/bin/curl.exe"):
        check_curl_available()  # should not raise
