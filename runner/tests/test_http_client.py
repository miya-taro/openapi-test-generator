import sys
from pathlib import Path
from unittest.mock import patch
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from http_client import execute_with_openapi, health_check, _resolve_auth_header
from models import EXIT_ERROR, EXIT_OK, EXIT_TIMEOUT, RunCase


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


def mock_send(status: int = 200, body: str = "", headers: dict | None = None, capture: list | None = None):
    """requests.Session.send を差し替えるフェイク。実際に送信される PreparedRequest を
    capture リストに記録するので、テスト側で送信内容（メソッド・ヘッダ・URL等）を検証できる。
    """
    def _send(self, prepared_request, **kwargs):
        if capture is not None:
            capture.append(prepared_request)
        resp = requests.Response()
        resp.status_code = status
        resp._content = body.encode("utf-8")
        resp.headers.update(headers or {})
        resp.request = prepared_request
        resp.url = prepared_request.url
        return resp
    return _send


# --- レスポンス解析 ---

def test_parse_200_response():
    case = make_case()
    with patch("requests.Session.send", mock_send(200, '{"items":[]}', {"Content-Type": "application/json"})):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_status == 200
    assert result.elapsed_ms >= 0
    assert result.actual_body == '{"items":[]}'
    assert result.exit_code == EXIT_OK
    assert result.error is None


def test_parse_400_response():
    case = make_case(input_value="0")
    with patch("requests.Session.send", mock_send(400, '{"error":"bad request"}', {"Content-Type": "application/json"})):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_status == 400


def test_response_headers_parsed():
    case = make_case()
    with patch("requests.Session.send", mock_send(200, "ok", {"Content-Type": "application/json"})):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.actual_headers.get("Content-Type") == "application/json"


def test_curl_command_stored():
    case = make_case()
    with patch("requests.Session.send", mock_send(200, "ok")):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.curl_command.startswith("curl.exe")
    assert "http://localhost:8080/users" in result.curl_command


def test_declared_cookie_parameter_is_sent_as_cookie_header():
    case = make_case(param_in="cookie", param_name="session_hint", input_value="abc123")
    openapi = {
        "paths": {
            "/users": {
                "get": {
                    "parameters": [{
                        "name": "session_hint", "in": "cookie", "required": True,
                        "schema": {"type": "string"},
                    }],
                },
            },
        },
    }
    captured = []
    with patch("requests.Session.send", mock_send(200, "ok", capture=captured)):
        execute_with_openapi(case, "http://localhost:8080", openapi)

    assert captured[0].headers["Cookie"] == "session_hint=abc123"


def test_required_header_omission_marker_sends_no_header():
    case = make_case(param_in="header", param_name="X-Client-Version", input_value="（フィールドを省略）")
    captured = []
    with patch("requests.Session.send", mock_send(400, capture=captured)):
        execute_with_openapi(case, "http://localhost:8080", None)

    assert "X-Client-Version" not in captured[0].headers


def test_required_header_empty_marker_sends_empty_header_value():
    case = make_case(param_in="header", param_name="X-Client-Version", input_value="（空文字）")
    captured = []
    with patch("requests.Session.send", mock_send(400, capture=captured)):
        execute_with_openapi(case, "http://localhost:8080", None)

    assert captured[0].headers["X-Client-Version"] == ""


def test_operation_baseline_sends_required_parameters_and_body():
    case = make_case(
        param_in="operation",
        param_name="__valid_request__",
        input_value="（最小有効リクエスト）",
        path="/users/{tenant}",
        method="POST",
    )
    openapi = {
        "paths": {
            "/users/{tenant}": {
                "post": {
                    "operationId": "createUser",
                    "parameters": [
                        {"name": "tenant", "in": "path", "required": True,
                         "schema": {"type": "string", "enum": ["north"]}},
                        {"name": "q", "in": "query", "required": True,
                         "schema": {"type": "integer", "minimum": 2}},
                        {"name": "X-Region", "in": "header", "required": True,
                         "schema": {"type": "string", "enum": ["west"]}},
                        {"name": "locale", "in": "cookie", "required": True,
                         "schema": {"type": "string", "enum": ["ja"]}},
                    ],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {"name": {"type": "string", "minLength": 2}},
                        }}},
                    },
                },
            },
        },
    }
    captured = []
    with patch("requests.Session.send", mock_send(201, "{}", capture=captured)):
        execute_with_openapi(case, "http://localhost:8080", openapi)

    request = captured[0]
    assert request.url == "http://localhost:8080/users/north?q=2"
    assert request.headers["X-Region"] == "west"
    assert request.headers["Cookie"] == "locale=ja"
    assert request.headers["Content-Type"].startswith("application/json")
    assert request.body == b'{"name": "aa"}'


# --- Session 共有・Cookie 永続化 ---

def test_session_passed_in_is_used_for_send():
    case = make_case()
    captured_self = []

    def _send(self, prepared_request, **kwargs):
        captured_self.append(self)
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"ok"
        return resp

    session = requests.Session()
    with patch("requests.Session.send", _send):
        execute_with_openapi(case, "http://localhost:8080", None, session)
    assert captured_self == [session]


def test_persist_cookies_false_clears_session_cookies_after_call():
    case = make_case()
    session = requests.Session()
    session.cookies.set("sid", "abc123")
    with patch("requests.Session.send", mock_send(200, "ok")):
        execute_with_openapi(case, "http://localhost:8080", None, session, persist_cookies=False)
    assert len(session.cookies) == 0


def test_persist_cookies_true_keeps_session_cookies():
    case = make_case()
    session = requests.Session()
    session.cookies.set("sid", "abc123")
    with patch("requests.Session.send", mock_send(200, "ok")):
        execute_with_openapi(case, "http://localhost:8080", None, session, persist_cookies=True)
    assert session.cookies.get("sid") == "abc123"


# --- エラー系 ---

def test_timeout_returns_error():
    case = make_case()

    def _send(self, prepared_request, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    with patch("requests.Session.send", _send):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.exit_code == EXIT_TIMEOUT
    assert result.actual_status == 0
    assert result.error is not None


def test_connection_error_returns_error():
    case = make_case()

    def _send(self, prepared_request, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    with patch("requests.Session.send", _send):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert result.exit_code == EXIT_ERROR
    assert result.actual_status == 0
    assert "connection refused" in result.error


# --- 認証ヘッダ ---

HEADER_201 = {"Content-Type": "application/json"}


def test_auth_token_added_when_env_set(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_TOKEN", "mytoken")
    case = make_case()
    capture: list = []
    with patch("requests.Session.send", mock_send(200, "ok", capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", None)
    assert capture[0].headers.get("Authorization") == "Bearer mytoken"


def test_auth_token_masked_in_stored_curl_command(monkeypatch):
    # 実行には実トークンを使うが、結果Excelに保存される curl_command には
    # 平文のトークンを残してはならない。
    monkeypatch.setenv("TEST_AUTH_TOKEN", "supersecrettoken")
    case = make_case()
    with patch("requests.Session.send", mock_send(200, "ok")):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert "supersecrettoken" not in result.curl_command
    assert "***MASKED***" in result.curl_command


def test_auth_header_env_masked_in_stored_curl_command(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "X-Api-Key")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "leaked-secret-value")
    monkeypatch.delenv("TEST_AUTH_TOKEN", raising=False)
    case = make_case()
    with patch("requests.Session.send", mock_send(200, "ok")):
        result = execute_with_openapi(case, "http://localhost:8080", None)
    assert "leaked-secret-value" not in result.curl_command
    assert "***MASKED***" in result.curl_command


def test_no_auth_header_without_token(monkeypatch):
    monkeypatch.delenv("TEST_AUTH_TOKEN", raising=False)
    case = make_case()
    capture: list = []
    with patch("requests.Session.send", mock_send(200, "ok", capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", None)
    assert "Authorization" not in capture[0].headers


def test_auth_probe_bundle_sends_all_invalid_credentials_and_excludes_session_cookies(monkeypatch):
    import json

    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "Authorization")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "Bearer valid-login-token")
    session = requests.Session()
    session.cookies.set("existing-session", "must-not-leak-into-probe")
    case = make_case(
        param_in="header",
        param_name="__openapi_security__",
        input_value=json.dumps({
            "headers": {"Authorization": "invalid-token-xxx", "X-Api-Key": "invalid-key"},
            "query": {"api_key": "invalid-query-key"},
            "cookies": {"session_key": "invalid-cookie"},
        }),
    )
    capture: list = []

    with patch("requests.Session.send", mock_send(401, "unauthorized", capture=capture)):
        result = execute_with_openapi(case, "http://localhost:8080", None, session, persist_cookies=True)

    prepared = capture[0]
    assert prepared.headers["Authorization"] == "invalid-token-xxx"
    assert prepared.headers["X-Api-Key"] == "invalid-key"
    assert prepared.headers["Cookie"] == "session_key=invalid-cookie"
    assert "existing-session" not in prepared.headers["Cookie"]
    assert "api_key=invalid-query-key" in prepared.url
    assert "valid-login-token" not in prepared.headers.values()
    assert "api_key=invalid-query-key" in result.curl_command
    assert '"X-Api-Key: invalid-key"' in result.curl_command
    assert '"Cookie: session_key=invalid-cookie"' in result.curl_command
    assert "valid-login-token" not in result.curl_command


def test_auth_none_probe_omits_environment_and_persisted_cookie_credentials(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "Authorization")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "Bearer valid-login-token")
    session = requests.Session()
    session.cookies.set("session", "valid-session-cookie")
    case = make_case(
        param_in="header",
        param_name="__openapi_security__",
        input_value="（認証ヘッダなし）",
    )
    capture: list = []

    with patch("requests.Session.send", mock_send(401, "unauthorized", capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", None, session, persist_cookies=True)

    assert "Authorization" not in capture[0].headers
    assert "Cookie" not in capture[0].headers


def test_auth_probe_does_not_mutate_persistent_session_cookie_jar():
    import json

    session = requests.Session()
    session.cookies.set("sid", "valid-session-cookie")
    case = make_case(
        param_in="header",
        param_name="__openapi_security__",
        input_value=json.dumps({"headers": {"Authorization": "invalid-token-xxx"}}),
    )
    senders = []

    def _send(self, prepared_request, **kwargs):
        senders.append(self)
        self.cookies.set("probe-cookie", "must-not-persist")
        return mock_send(401, "unauthorized")(self, prepared_request, **kwargs)

    with patch("requests.Session.send", _send):
        execute_with_openapi(case, "http://localhost:8080", None, session, persist_cookies=True)

    assert len(senders) == 1
    assert senders[0] is not session
    assert session.cookies.get("sid") == "valid-session-cookie"
    assert session.cookies.get("probe-cookie") is None


# --- body / Content-Type ---

def test_body_param_adds_json_content_type():
    case = make_case(
        method="POST", param_in="body", param_name="name", input_value="Alice"
    )
    capture: list = []
    with patch("requests.Session.send", mock_send(201, '{"id":1}', HEADER_201, capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", None)
    assert capture[0].headers.get("Content-Type", "").startswith("application/json")
    assert capture[0].body is not None


def test_unsupported_content_type_probe_keeps_valid_json_body_and_header():
    case = make_case(
        operation_id="createUser", path="/users", method="POST",
        param_in="header", param_name="Content-Type", input_value="text/plain",
    )
    openapi = {"paths": {"/users": {"post": {
        "operationId": "createUser",
        "requestBody": {"required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["name", "email"],
            "properties": {"name": {"type": "string"}, "email": {"type": "string", "format": "email"}},
        }}}},
    }}}}
    capture: list = []
    with patch("requests.Session.send", mock_send(415, "unsupported", capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", openapi)
    assert capture[0].headers.get("Content-Type") == "text/plain"
    assert capture[0].body is not None
    assert b'"name": "test"' in capture[0].body
    assert b'"email": "test@example.com"' in capture[0].body


MULTIPART_OPENAPI = {
    "paths": {
        "/avatars": {
            "post": {
                "operationId": "uploadAvatar",
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["caption"],
                                "properties": {"caption": {"type": "string", "minLength": 1}},
                            }
                        }
                    }
                },
            }
        }
    }
}


def test_multipart_body_does_not_add_json_content_type():
    case = make_case(
        operation_id="uploadAvatar", path="/avatars", method="POST",
        param_in="body", param_name="caption", input_value="hello",
    )
    capture: list = []
    with patch("requests.Session.send", mock_send(201, '{"id":1}', HEADER_201, capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", MULTIPART_OPENAPI)
    content_type = capture[0].headers.get("Content-Type", "")
    assert content_type.startswith("multipart/form-data")
    assert not content_type.startswith("application/json")


def test_unsupported_content_type_probe_keeps_valid_multipart_body_and_header():
    case = make_case(
        operation_id="uploadAvatar", path="/avatars", method="POST",
        param_in="header", param_name="Content-Type", input_value="application/x-invalid",
    )
    capture: list = []
    with patch("requests.Session.send", mock_send(415, "unsupported", capture=capture)):
        execute_with_openapi(case, "http://localhost:8080", MULTIPART_OPENAPI)
    assert capture[0].headers.get("Content-Type") == "application/x-invalid"
    assert capture[0].body is not None
    assert b'name="caption"' in capture[0].body
    assert b"\r\na\r\n" in capture[0].body


# --- health_check tests ---

def test_health_check_success():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        assert health_check("http://localhost:8080") is True


def test_health_check_failure_5xx():
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 503
        assert health_check("http://localhost:8080") is False


def test_health_check_connection_error():
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError):
        assert health_check("http://localhost:8080") is False


# --- _resolve_auth_header priority tests ---

def test_header_env_takes_priority_over_legacy_token(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "X-Api-Key")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "abc123")
    monkeypatch.setenv("TEST_AUTH_TOKEN", "legacytoken")
    assert _resolve_auth_header() == "X-Api-Key: abc123"


def test_falls_back_to_legacy_token_when_header_env_unset(monkeypatch):
    monkeypatch.delenv("TEST_AUTH_HEADER_NAME", raising=False)
    monkeypatch.delenv("TEST_AUTH_HEADER_VALUE", raising=False)
    monkeypatch.setenv("TEST_AUTH_TOKEN", "legacytoken")
    assert _resolve_auth_header() == "Authorization: Bearer legacytoken"


def test_no_header_when_only_name_set(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "X-Api-Key")
    monkeypatch.delenv("TEST_AUTH_HEADER_VALUE", raising=False)
    monkeypatch.delenv("TEST_AUTH_TOKEN", raising=False)
    assert _resolve_auth_header() is None


def test_prepared_request_preserves_environment_ca_bundle_and_proxy(monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/configured/trust.pem")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("https_proxy", "http://proxy.example:8080")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    captured = []

    def send(self, prepared_request, **kwargs):
        captured.append(kwargs)
        return mock_send(200, "{}")(self, prepared_request, **kwargs)

    with patch("requests.Session.send", send):
        result = execute_with_openapi(make_case(), "https://api.example", None)
    assert result.exit_code == EXIT_OK
    assert captured[0]["verify"] == "/configured/trust.pem"
    assert captured[0]["proxies"]["https"] == "http://proxy.example:8080"
    assert captured[0]["allow_redirects"] is False


def test_prepared_request_preserves_session_tls_settings(monkeypatch):
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/environment/ignored.pem")
    session = requests.Session()
    session.trust_env = False
    session.verify = "/session/trust.pem"
    session.cert = ("/session/client.pem", "/session/client.key")
    captured = []

    def send(self, prepared_request, **kwargs):
        captured.append(kwargs)
        return mock_send(200, "{}")(self, prepared_request, **kwargs)

    with patch("requests.Session.send", send):
        execute_with_openapi(make_case(), "https://api.example", None, session)
    assert captured[0]["verify"] == session.verify
    assert captured[0]["cert"] == session.cert
    assert captured[0]["proxies"] == {}


def test_prepared_request_keeps_certificate_verification_enabled(monkeypatch):
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    captured = []

    def send(self, prepared_request, **kwargs):
        captured.append(kwargs)
        return mock_send(200, "{}")(self, prepared_request, **kwargs)

    with patch("requests.Session.send", send):
        execute_with_openapi(make_case(), "https://api.example", None)
    assert captured[0]["verify"] is True
