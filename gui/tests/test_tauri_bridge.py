"""tauri_bridge.py（Tauri版GUIからvalidators.pyを呼び出す薄いブリッジ）のテスト。

サブプロセスを実際に起動せず、_dispatch()を直接呼んでロジックだけを検証する
（プロセス起動・stdin/stdout周りはRust側の責務であり、ここでは検証しない）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tauri_bridge


def test_dispatch_list_operations(tmp_path):
    doc = {"openapi": "3.0.3", "paths": {"/users": {"get": {"operationId": "listUsers"}}}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = tauri_bridge._dispatch("list_operations", {"path": str(path)})

    assert result == [{"operationId": "listUsers", "method": "GET", "path": "/users"}]


def test_dispatch_validate_openapi(tmp_path):
    doc = {"openapi": "3.0.3", "paths": {}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = tauri_bridge._dispatch("validate_openapi", {"path": str(path)})

    assert result.startswith("OK")


def test_dispatch_login_operation_hints(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "paths": {
            "/auth/login": {
                "post": {
                    "operationId": "login",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["email"],
                                    "properties": {"email": {"type": "string"}},
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    result = tauri_bridge._dispatch("login_operation_hints", {"path": str(path), "operation_id": "login"})

    assert result == {"body": {"email": "email"}, "token_path": None}


def test_dispatch_health_check_unreachable_host():
    result = tauri_bridge._dispatch("health_check", {"base_url": "http://127.0.0.1:1", "health_path": "/health"})
    assert result is False


def test_dispatch_unknown_command_raises():
    try:
        tauri_bridge._dispatch("nope", {})
        assert False, "should have raised"
    except ValueError as e:
        assert "nope" in str(e)


def test_servers_url_returns_first_server(tmp_path):
    doc = {"openapi": "3.0.3", "servers": [{"url": "https://api.example.com"}], "paths": {}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    assert tauri_bridge._servers_url(str(path)) == "https://api.example.com"


def test_servers_url_missing_file_returns_none(tmp_path):
    assert tauri_bridge._servers_url(str(tmp_path / "missing.json")) is None


def test_servers_url_no_servers_key_returns_none(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps({"openapi": "3.0.3", "paths": {}}), encoding="utf-8")

    assert tauri_bridge._servers_url(str(path)) is None


def test_main_writes_ok_json_to_stdout(tmp_path, monkeypatch, capsys):
    doc = {"openapi": "3.0.3", "paths": {}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    request = json.dumps({"command": "validate_openapi", "args": {"path": str(path)}})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(request))

    code = tauri_bridge.main()

    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["result"].startswith("OK")


def test_main_writes_error_json_on_unknown_command(monkeypatch, capsys):
    request = json.dumps({"command": "nope", "args": {}})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(request))

    code = tauri_bridge.main()

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert "nope" in output["error"]
