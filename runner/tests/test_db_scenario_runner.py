import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import db_scenario_runner as dsr_module

MINIMAL_OPENAPI = {
    "openapi": "3.1.0",
    "paths": {
        "/users": {
            "post": {"operationId": "createUser", "responses": {"201": {"description": "Created"}}}
        },
        "/users/{id}": {
            "put": {"operationId": "updateUser", "responses": {"200": {"description": "OK"}}}
        },
    },
}

CONFIG = {
    "postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"},
    "influxdb": {"host": "h", "port": 8086, "database": "m"},
}


def _write_files(tmp_path, scenarios_data: dict) -> tuple[Path, Path, Path]:
    scenario_path = tmp_path / "scenarios.yaml"
    scenario_path.write_text(yaml.dump(scenarios_data, allow_unicode=True), encoding="utf-8")
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(MINIMAL_OPENAPI), encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
    return scenario_path, openapi_path, config_path


def run_main(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["db_scenario_runner.py", *argv])
    return dsr_module.main()


def _patch_common(monkeypatch):
    monkeypatch.setattr(dsr_module, "check_curl_available", lambda: None)
    monkeypatch.setattr(dsr_module, "health_check", lambda base_url, health_path: True)


# ---------- _resolve_operation ----------


def test_resolve_operation_finds_path_and_method():
    path, method = dsr_module._resolve_operation(MINIMAL_OPENAPI, "createUser")
    assert path == "/users"
    assert method == "POST"


def test_resolve_operation_unknown_raises():
    with pytest.raises(dsr_module.ScenarioError, match="unknownOp"):
        dsr_module._resolve_operation(MINIMAL_OPENAPI, "unknownOp")


# ---------- _call_api ----------


def test_call_api_builds_url_with_path_params_and_parses_status(monkeypatch):
    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 5}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    status, response, error = dsr_module._call_api(
        "http://x", "/users/{id}", "PUT", {"id": 5}, {"name": "updated"}
    )
    assert status == 201
    assert response == {"id": 5}
    assert error is None
    assert "http://x/users/5" in captured_cmd["cmd"]


def test_call_api_omits_body_flag_when_body_empty(monkeypatch):
    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        result = MagicMock()
        result.returncode = 0
        result.stdout = "\n204"
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    status, response, error = dsr_module._call_api("http://x", "/users/1", "DELETE", {}, {})
    assert status == 204
    assert "-d" not in captured_cmd["cmd"]


def test_call_api_curl_not_found(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    status, response, error = dsr_module._call_api("http://x", "/users", "POST", {}, {"a": 1})
    assert error is not None
    assert status == 0


def test_call_api_nonzero_exit_returns_error(monkeypatch):
    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 7
        result.stderr = "connection refused"
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    status, response, error = dsr_module._call_api("http://x", "/users", "POST", {}, {})
    assert error == "connection refused"


def test_call_api_invalid_json_body_falls_back_to_empty_dict(monkeypatch):
    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "not json\n200"
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    status, response, error = dsr_module._call_api("http://x", "/users", "GET", {}, {})
    assert status == 200
    assert response == {}
    assert error is None


# ---------- main(): 引数検証・存在確認 ----------


def test_missing_scenario_file_returns_3(monkeypatch, tmp_path):
    _, openapi_path, config_path = _write_files(tmp_path, {"scenarios": []})
    code = run_main(
        monkeypatch,
        [str(tmp_path / "nope.yaml"), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 3


def test_missing_openapi_file_returns_3(monkeypatch, tmp_path):
    scenario_path, _, config_path = _write_files(tmp_path, {"scenarios": []})
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(tmp_path / "nope.json"), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 3


def test_invalid_scenario_yaml_returns_3(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, {"not_scenarios": []})
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 3


def test_health_check_failure_returns_3(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, {"scenarios": []})
    monkeypatch.setattr(dsr_module, "check_curl_available", lambda: None)
    monkeypatch.setattr(dsr_module, "health_check", lambda base_url, health_path: False)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 3


def test_zero_scenarios_returns_0(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, {"scenarios": []})
    _patch_common(monkeypatch)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0


# ---------- main(): シナリオ実行の分岐（postgres_backend/influx_backendをフェイクに差し替え） ----------


def _one_postgres_scenario():
    return {
        "scenarios": [
            {
                "name": "ユーザー作成",
                "request": {"operationId": "createUser", "body": {"name": "太郎"}},
                "db_check": {"engine": "postgres", "table": "users", "where": {"id": "{{response.id}}"}, "expect": {}},
            }
        ]
    }


def test_scenario_pass_returns_0(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 5}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0
    assert "[OK]" in capsys.readouterr().out


def test_scenario_fail_returns_1_and_prints_detail(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 5}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    monkeypatch.setattr(
        dsr_module.postgres_backend, "check", lambda check, config: (False, "該当する行が見つかりません")
    )

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "[NG]" in out
    assert "該当する行が見つかりません" in out


def test_scenario_placeholder_resolution_passes_resolved_where_to_backend(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 42}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    captured = {}

    def fake_check(check, config):
        captured["where"] = check.where
        return True, ""

    monkeypatch.setattr(dsr_module.postgres_backend, "check", fake_check)

    run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert captured["where"] == {"id": 42}


def test_unresolvable_placeholder_marks_scenario_ng(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"unrelated_field": 1}\n201'  # id が返らない
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1
    assert "[NG]" in capsys.readouterr().out


def test_unknown_operation_id_marks_scenario_ng(monkeypatch, tmp_path):
    data = {
        "scenarios": [
            {
                "name": "存在しないop",
                "request": {"operationId": "doesNotExist", "body": {}},
                "db_check": {"engine": "postgres", "table": "t", "expect": {}},
            }
        ]
    }
    scenario_path, openapi_path, config_path = _write_files(tmp_path, data)
    _patch_common(monkeypatch)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1


def test_influxdb_scenario_dispatches_to_influx_backend(monkeypatch, tmp_path):
    data = {
        "scenarios": [
            {
                "name": "センサー",
                "request": {"operationId": "createUser", "body": {}},
                "db_check": {"engine": "influxdb", "measurement": "m", "tags": {}, "expect": {}},
            }
        ]
    }
    scenario_path, openapi_path, config_path = _write_files(tmp_path, data)
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "{}\n201"
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    called = {"hit": False}

    def fake_influx_check(check, config):
        called["hit"] = True
        return True, ""

    monkeypatch.setattr(dsr_module.influx_backend, "check", fake_influx_check)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert called.get("hit") is True
    assert code == 0
