import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from auth_login import (
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


# --- perform_login ---

def mock_curl(body_and_status: str, returncode: int = 0):
    m = MagicMock()
    m.stdout = body_and_status
    m.stderr = ""
    m.returncode = returncode
    return m


def test_perform_login_success_default_token_path():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"access_token":"tok123"}\n200')
        token = perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})
    assert token == "tok123"


def test_perform_login_sends_body_and_url():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"access_token":"tok123"}\n200')
        perform_login(
            "http://localhost:8080",
            {"login_url": "/login", "method": "POST", "body": {"user": "alice"}},
        )
        cmd = mock_run.call_args[0][0]
    joined = " ".join(cmd)
    assert "http://localhost:8080/login" in joined
    assert "-d" in cmd
    assert json.dumps({"user": "alice"}, ensure_ascii=False) in cmd


def test_perform_login_nested_token_path():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"data":{"token":"nested123"}}\n200')
        token = perform_login(
            "http://localhost:8080",
            {"login_url": "/login", "method": "POST", "token_path": "data.token"},
        )
    assert token == "nested123"


def test_perform_login_non_2xx_status():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"error":"invalid credentials"}\n401')
        with pytest.raises(AuthLoginError, match="401"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_curl_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(AuthLoginError, match="curl.exe"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_curl_nonzero_exit():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl("", returncode=28)
        with pytest.raises(AuthLoginError, match="実行に失敗"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_unparseable_status():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl("garbage output with no newline-status")
        with pytest.raises(AuthLoginError, match="解析できませんでした"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_invalid_response_json():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl("not json\n200")
        with pytest.raises(AuthLoginError, match="JSONとして解析できません"):
            perform_login("http://localhost:8080", {"login_url": "/login", "method": "POST"})


def test_perform_login_token_not_found_in_response():
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = mock_curl('{"unrelated":"field"}\n200')
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
