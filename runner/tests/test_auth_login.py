import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from auth_login import (
    auth_config_for_profile,
    load_auth_config,
    perform_login,
    build_auth_header,
    _extract_token,
    AuthLoginError,
)


# --- load_auth_config ---

def test_load_auth_config_missing_file():
    with pytest.raises(AuthLoginError, match="見つかりません"):
        load_auth_config("does_not_exist.json")


def test_load_auth_config_invalid_json(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(AuthLoginError, match="パースに失敗"):
        load_auth_config(str(p))


def test_load_auth_config_not_an_object(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(AuthLoginError, match="オブジェクトである必要"):
        load_auth_config(str(p))


def test_load_auth_config_missing_required_keys(tmp_path):
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"method": "POST"}), encoding="utf-8")
    with pytest.raises(AuthLoginError, match="login_url"):
        load_auth_config(str(p))


def test_load_auth_config_success(tmp_path):
    cfg = {"login_url": "/login", "method": "POST", "body": {"user": "a"}}
    p = tmp_path / "auth.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    result = load_auth_config(str(p))
    assert result == cfg


def test_load_auth_config_accepts_named_login_profiles(tmp_path):
    cfg = {
        "login_url": "/login",
        "method": "POST",
        "body": {"username": "default", "password": "secret"},
        "auth_profiles": {"reader": {"username": "readonly", "password": "reader-secret"}},
    }
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    assert load_auth_config(str(path)) == cfg
    assert auth_config_for_profile(cfg, None)["body"] == cfg["body"]
    assert auth_config_for_profile(cfg, "reader")["body"] == cfg["auth_profiles"]["reader"]


@pytest.mark.parametrize("profiles", [[], {"bad name": {"username": "x"}}, {"reader": []}])
def test_load_auth_config_rejects_invalid_named_profiles(tmp_path, profiles):
    path = tmp_path / "auth.json"
    path.write_text(json.dumps({"login_url": "/login", "method": "POST", "auth_profiles": profiles}), encoding="utf-8")

    with pytest.raises(AuthLoginError, match="プロファイル"):
        load_auth_config(str(path))


def test_auth_config_for_unknown_profile_has_safe_error():
    cfg = {"login_url": "/login", "method": "POST", "auth_profiles": {"reader": {"user": "x"}}}
    with pytest.raises(AuthLoginError, match="見つかりません"):
        auth_config_for_profile(cfg, "admin")


def test_load_auth_config_yaml_with_comments(tmp_path):
    # examples/auth_config.yaml のような、コメントと未使用項目を含むYAMLも読めること
    p = tmp_path / "auth.yaml"
    p.write_text(
        """
# これはコメント。ログイン方式の認証設定。
login_url: /login
method: POST
body:
  username: test-user
  password: test-pass

# 以下は未使用の代替設定（コメントアウト）
# token_path: data.token
# header_name: X-Api-Key
# header_format: "{token}"
""",
        encoding="utf-8",
    )
    result = load_auth_config(str(p))
    assert result == {
        "login_url": "/login",
        "method": "POST",
        "body": {"username": "test-user", "password": "test-pass"},
    }


def test_load_auth_config_invalid_yaml_syntax(tmp_path):
    p = tmp_path / "auth.yaml"
    p.write_text("login_url: /login\n  bad_indent: [1, 2\nmethod: POST", encoding="utf-8")
    with pytest.raises(AuthLoginError, match="パースに失敗"):
        load_auth_config(str(p))


# --- perform_login ---

def mock_response(status: int = 200, body: str = "") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode("utf-8")
    return resp


def test_perform_login_success_default_token_path():
    with patch("requests.request", return_value=mock_response(200, '{"access_token":"tok123"}')):
        token = perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})
    assert token == "tok123"


def test_perform_login_sends_body_and_url():
    with patch("requests.request", return_value=mock_response(200, '{"access_token":"tok123"}')) as mock_req:
        perform_login(
            "http://localhost:8080",
            {"login_url": "/login", "method": "POST", "body": {"user": "alice"}},
        )
    args, kwargs = mock_req.call_args
    assert args[0] == "POST"
    assert args[1] == "http://localhost:8080/login"
    assert kwargs["json"] == {"user": "alice"}


def test_perform_login_with_session_shares_cookies():
    session = requests.Session()
    captured_self = []

    def _request(self, method, url, **kwargs):
        captured_self.append(self)
        return mock_response(200, '{"access_token":"tok123"}')

    with patch("requests.Session.request", _request):
        perform_login(
            "http://localhost:8080",
            {"login_url": "/login", "method": "POST"},
            session=session,
        )
    # session.request（インスタンスメソッド）経由で呼ばれ、そのSessionが後続の全リクエストと
    # 共有されることで、ログイン時に発行されたセッションCookieが自動的に引き継がれる。
    assert captured_self == [session]


def test_perform_login_without_session_uses_module_level_request():
    with patch("requests.request", return_value=mock_response(200, '{"access_token":"tok123"}')) as mock_req:
        perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})
    assert mock_req.called


def test_perform_login_nested_token_path():
    with patch("requests.request", return_value=mock_response(200, '{"data":{"token":"nested123"}}')):
        token = perform_login(
            "http://localhost:8080",
            {"login_url": "/login", "method": "POST", "token_path": "data.token"},
        )
    assert token == "nested123"


def test_perform_login_non_2xx_status():
    with patch("requests.request", return_value=mock_response(401, '{"password":"must-not-leak"}')):
        with pytest.raises(AuthLoginError, match="401") as error:
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})
    assert "must-not-leak" not in str(error.value)


def test_perform_login_connection_error():
    with patch("requests.request", side_effect=requests.exceptions.ConnectionError("refused")):
        with pytest.raises(AuthLoginError, match="実行に失敗"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_timeout():
    with patch("requests.request", side_effect=requests.exceptions.Timeout("timed out")):
        with pytest.raises(AuthLoginError, match="実行に失敗"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_invalid_response_json():
    with patch("requests.request", return_value=mock_response(200, "secret-fragment not json")):
        with pytest.raises(AuthLoginError, match="JSONとして解析できません") as error:
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})
    assert "secret-fragment" not in str(error.value)


def test_perform_login_token_not_found_in_response():
    with patch("requests.request", return_value=mock_response(200, '{"unrelated":"field"}')):
        with pytest.raises(AuthLoginError, match="トークンを取得できませんでした"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


# --- _extract_token ---

def test_extract_token_top_level():
    assert _extract_token({"access_token": "tok"}, "access_token") == "tok"


def test_extract_token_nested():
    assert _extract_token({"data": {"token": "tok"}}, "data.token") == "tok"


def test_extract_token_missing_returns_none():
    assert _extract_token({"foo": "bar"}, "access_token") is None


def test_extract_token_non_dict_intermediate_returns_none():
    assert _extract_token({"data": "not_a_dict"}, "data.token") is None


# --- build_auth_header ---

def test_build_auth_header_defaults():
    name, value = build_auth_header("tok123", {})
    assert name == "Authorization"
    assert value == "Bearer tok123"


def test_build_auth_header_custom():
    name, value = build_auth_header(
        "tok123", {"header_name": "X-Api-Key", "header_format": "Token {token}"}
    )
    assert name == "X-Api-Key"
    assert value == "Token tok123"


def test_login_redaction_marks_only_selected_response_path():
    from auth_login import mark_login_response_sensitive
    schema = {'type':'object','properties':{'data':{'type':'object','properties':{'id':{'type':'string'}}},'id':{'type':'string'}}}
    response = {'200':{'content':{'application/json':{'schema':schema}}}}
    api = {'paths':{'/login':{'post':{'responses':response}},'/other':{'get':{'responses':response}}}}
    mark_login_response_sensitive(api,{'login_url':'/login','method':'POST','token_path':'data.id'})
    login_schema=api['paths']['/login']['post']['responses']['200']['content']['application/json']['schema']
    assert login_schema['properties']['data']['properties']['id']['x-api-tester-sensitive'] is True
    assert 'x-api-tester-sensitive' not in login_schema['properties']['id']
    assert 'x-api-tester-sensitive' not in schema['properties']['data']['properties']['id']
    mark_login_response_sensitive(None,{'login_url':'/login'})
