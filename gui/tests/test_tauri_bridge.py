"""tauri_bridge.py（Tauri版GUIからvalidators.pyを呼び出す薄いブリッジ）のテスト。

サブプロセスを実際に起動せず、_dispatch()を直接呼んでロジックだけを検証する
（プロセス起動・stdin/stdout周りはRust側の責務であり、ここでは検証しない）。
"""
import json
import sys
from pathlib import Path

import pytest

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


def test_dispatch_loads_and_saves_operation_body_contract(tmp_path):
    source = tmp_path / "openapi.json"
    destination = tmp_path / "openapi.ui-edited.json"
    source.write_text(json.dumps({
        "openapi": "3.0.3",
        "paths": {"/users": {"post": {
            "operationId": "createUser",
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": {"type": "object", "required": ["email"],
                           "properties": {"email": {"type": "string"}}},
            }}},
            "responses": {"201": {"description": "Created"}},
        }}},
    }), encoding="utf-8")

    loaded = tauri_bridge._dispatch("load_operation_body_contract", {
        "path": str(source), "operation_id": "createUser",
    })
    saved = tauri_bridge._dispatch("save_operation_body_contract", {
        "source_path": str(source),
        "destination_path": str(destination),
        "operation_id": "createUser",
        "request_body_required": True,
        "request_body_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
        "response_status": "201",
        "response_body_schema": {"type": "object", "properties": {"id": {"type": "integer"}}},
    })

    assert loaded["requestBodyRequired"] is True
    assert loaded["responseStatus"] == "201"
    assert saved["path"] == str(destination.resolve())


def test_dispatch_health_check_unreachable_host():
    result = tauri_bridge._dispatch("health_check", {"base_url": "http://127.0.0.1:1", "health_path": "/health"})
    assert result is False


def test_dispatch_unknown_command_raises():
    with pytest.raises(ValueError, match="nope"):
        tauri_bridge._dispatch("nope", {})


def test_dispatch_loads_and_saves_case_master_review_state(tmp_path):
    master_path = tmp_path / "case-master.json"
    from workflow.case_master import write_case_master

    write_case_master({
        "format": "api-tester.case-master", "schemaVersion": 1,
        "project": {"name": "sample"},
        "cases": [{"caseId": "TC-1", "kind": "contract", "title": "case",
                   "source": {}, "definition": {}, "expected": {}, "reviewStatus": "draft"}],
    }, master_path)

    loaded = tauri_bridge._dispatch("load_case_master", {"path": str(master_path)})
    saved = tauri_bridge._dispatch("save_case_master_reviews", {
        "path": str(master_path), "updates": {"TC-1": "reviewed"},
    })

    assert loaded["cases"][0]["caseId"] == "TC-1"
    assert saved["cases"][0]["reviewStatus"] == "reviewed"


def test_dispatch_loads_only_valid_failed_case_ids(tmp_path):
    path = tmp_path / "failed-case-ids.json"
    path.write_text('["TC-1", "DB-case-2"]', encoding="utf-8")

    result = tauri_bridge._dispatch("load_failed_case_ids", {"path": str(path)})

    assert result == ["TC-1", "DB-case-2"]


def test_dispatch_load_project_returns_only_public_project_fields(tmp_path):
    project = tmp_path / "project.json"
    project.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "name": "orders",
                "openapiPath": "openapi.json",
                "baseUrl": "https://vm.local/api",
                "outputDir": "results",
                "selectedOperations": ["getOrders"],
            }
        ),
        encoding="utf-8",
    )

    result = tauri_bridge._dispatch("load_project", {"path": str(project)})

    assert result == {
        "schemaVersion": 1,
        "name": "orders",
        "openapiPath": str((tmp_path / "openapi.json").resolve()),
        "baseUrl": "https://vm.local/api",
        "outputDir": str((tmp_path / "results").resolve()),
        "selectedOperations": ["getOrders"],
        "setupSqlPath": None,
        "teardownSqlPath": None,
        "dbScenariosPath": None,
    }


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
