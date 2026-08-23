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


# ---------- シナリオ間の {{response.xxx}} 連携（path_params / body） ----------


def _create_then_update_scenarios():
    return {
        "scenarios": [
            {
                "name": "ユーザー作成",
                "request": {"operationId": "createUser", "body": {"name": "太郎"}},
                "db_check": {"engine": "postgres", "table": "users", "where": {"id": "{{response.id}}"}, "expect": {}},
            },
            {
                "name": "作成したユーザーを更新",
                "request": {
                    "operationId": "updateUser",
                    "path_params": {"id": "{{response.id}}"},
                    "body": {"name": "次郎"},
                },
                "db_check": {"engine": "postgres", "table": "users", "where": {"id": "{{response.id}}"}, "expect": {}},
            },
        ]
    }


def test_path_params_resolved_from_previous_scenario_response(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _create_then_update_scenarios())
    _patch_common(monkeypatch)
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        if len(calls) == 1:
            result.stdout = '{"id": 42}\n201'
        else:
            result.stdout = '{"id": 42, "name": "次郎"}\n200'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0
    assert len(calls) == 2
    # path_params の {{response.id}} が前段シナリオの id=42 に解決され、URLに反映されていること
    assert any("/users/42" in arg for arg in calls[1])
    assert not any("{{response.id}}" in arg for arg in calls[1])


def test_body_resolved_from_previous_scenario_response(monkeypatch, tmp_path):
    data = {
        "scenarios": [
            {
                "name": "ユーザー作成",
                "request": {"operationId": "createUser", "body": {"name": "太郎"}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
            },
            {
                "name": "作成したユーザーIDを紐づけて注文作成",
                "request": {"operationId": "createUser", "body": {"linked_user_id": "{{response.id}}"}},
                "db_check": {"engine": "postgres", "table": "orders", "where": {}, "expect": {}},
            },
        ]
    }
    scenario_path, openapi_path, config_path = _write_files(tmp_path, data)
    _patch_common(monkeypatch)
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 99}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0
    second_body = calls[1][calls[1].index("-d") + 1]
    assert json.loads(second_body) == {"linked_user_id": 99}


def test_path_params_placeholder_with_no_previous_scenario_marks_ng(monkeypatch, tmp_path, capsys):
    # 1件目からいきなり {{response.id}} を参照している場合、前段のレスポンスが空なので解決に失敗する
    data = {
        "scenarios": [
            {
                "name": "前段なしでいきなり更新",
                "request": {"operationId": "updateUser", "path_params": {"id": "{{response.id}}"}, "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
            }
        ]
    }
    scenario_path, openapi_path, config_path = _write_files(tmp_path, data)
    _patch_common(monkeypatch)

    def fail_if_called(cmd, **kwargs):
        raise AssertionError("解決に失敗した時点でcurlを呼んではいけない")

    monkeypatch.setattr(dsr_module.subprocess, "run", fail_if_called)

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "[NG]" in out
    assert "値解決に失敗" in out


def test_previous_response_updates_to_most_recent_scenario_only(monkeypatch, tmp_path):
    # 3シナリオ連鎖: 2番目の path_params は1番目のレスポンス、3番目の path_params は
    # （1番目ではなく）2番目のレスポンスを参照すること（常に「直前」のレスポンスであること）
    data = {
        "scenarios": [
            {
                "name": "1件目",
                "request": {"operationId": "createUser", "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
            },
            {
                "name": "2件目",
                "request": {"operationId": "updateUser", "path_params": {"id": "{{response.id}}"}, "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
            },
            {
                "name": "3件目",
                "request": {"operationId": "updateUser", "path_params": {"id": "{{response.id}}"}, "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
            },
        ]
    }
    scenario_path, openapi_path, config_path = _write_files(tmp_path, data)
    _patch_common(monkeypatch)
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        # 1件目はid=1を、2件目はid=2を返す。3件目のURLはid=2を参照すべき（id=1ではない）
        stdout_by_call = ['{"id": 1}\n201', '{"id": 2}\n200', '{"id": 2}\n200']
        result.stdout = stdout_by_call[len(calls) - 1]
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0
    assert any("/users/1" in arg for arg in calls[1])
    assert any("/users/2" in arg for arg in calls[2])


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


# ---------- main(): response_check（APIレスポンス自体の検証） ----------


def _one_response_check_scenario():
    return {
        "scenarios": [
            {
                "name": "最大値のユーザーを取得できる",
                "request": {"operationId": "createUser", "body": {}},
                "response_check": {"expect": {"status": 201, "body": {"price": 99999999.99}}},
            }
        ]
    }


def test_response_check_only_scenario_passes(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_response_check_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"price": 99999999.99}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0


def test_response_check_only_scenario_fails_with_detail(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_response_check_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"price": 1}\n201'  # 期待値(99999999.99)と異なる
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "[NG]" in out
    assert "price" in out


def test_response_check_status_mismatch_marks_ng(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_response_check_scenario())
    _patch_common(monkeypatch)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"price": 99999999.99}\n404'  # statusが期待(201)と異なる
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 1
    assert "[NG]" in capsys.readouterr().out


def test_response_check_and_db_check_combined_both_must_pass(monkeypatch, tmp_path, capsys):
    data = {
        "scenarios": [
            {
                "name": "作成もDBもレスポンスも確認",
                "request": {"operationId": "createUser", "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
                "response_check": {"expect": {"status": 201}},
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
    # db_check側はNG、response_check側はOKにする → 全体としてNGになるはず
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


def test_response_check_and_db_check_both_pass_marks_ok(monkeypatch, tmp_path):
    data = {
        "scenarios": [
            {
                "name": "作成もDBもレスポンスも確認",
                "request": {"operationId": "createUser", "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "where": {}, "expect": {}},
                "response_check": {"expect": {"status": 201}},
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
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path)],
    )
    assert code == 0


# ---------- main(): --auth-config ----------


def test_auth_config_login_failure_returns_3(monkeypatch, tmp_path):
    # main() は os.environ を直接書き換える。monkeypatch.delenv(raising=False) は
    # キーが元々存在しない場合は何も記録しないため、テスト終了後に main() が新規
    # 設定した値が残ってしまう。setenv で一旦触れておくことで「元は未設定だった」
    # ことを monkeypatch に記録させ、テスト終了時に確実に削除させる。
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "__placeholder__")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "__placeholder__")
    scenario_path, openapi_path, config_path = _write_files(tmp_path, {"scenarios": []})
    _patch_common(monkeypatch)
    auth_config_path = tmp_path / "auth.json"
    auth_config_path.write_text(
        json.dumps({"login_url": "/login", "method": "POST"}), encoding="utf-8"
    )

    def fake_perform_login(base_url, auth_cfg):
        raise dsr_module.AuthLoginError("ログイン失敗")

    monkeypatch.setattr(dsr_module, "perform_login", fake_perform_login)
    code = run_main(
        monkeypatch,
        [
            str(scenario_path), str(openapi_path), "--base-url", "http://x",
            "--config", str(config_path), "--auth-config", str(auth_config_path),
        ],
    )
    assert code == 3


def test_auth_config_success_sets_env_and_call_api_sends_header(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "__placeholder__")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "__placeholder__")
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    _patch_common(monkeypatch)
    auth_config_path = tmp_path / "auth.json"
    auth_config_path.write_text(
        json.dumps({"login_url": "/login", "method": "POST"}), encoding="utf-8"
    )

    monkeypatch.setattr(dsr_module, "perform_login", lambda base_url, auth_cfg: "tok123")
    monkeypatch.setattr(dsr_module.postgres_backend, "check", lambda check, config: (True, ""))

    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        result = MagicMock()
        result.returncode = 0
        result.stdout = '{"id": 5}\n201'
        return result

    monkeypatch.setattr(dsr_module.subprocess, "run", fake_run)

    code = run_main(
        monkeypatch,
        [
            str(scenario_path), str(openapi_path), "--base-url", "http://x",
            "--config", str(config_path), "--auth-config", str(auth_config_path),
        ],
    )
    assert code == 0
    assert "Authorization: Bearer tok123" in " ".join(captured_cmd["cmd"])


# ---------- main(): --dry-run ----------


def test_dry_run_returns_0_without_executing(monkeypatch, tmp_path, capsys):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, _one_postgres_scenario())
    # dry-run はネットワーク・DBに触れないため、触れたら失敗するようフェイクを仕込む
    monkeypatch.setattr(dsr_module, "check_curl_available", lambda: (_ for _ in ()).throw(AssertionError("called")))
    monkeypatch.setattr(dsr_module, "health_check", lambda base_url, health_path: (_ for _ in ()).throw(AssertionError("called")))
    monkeypatch.setattr(dsr_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    monkeypatch.setattr(
        dsr_module.postgres_backend, "check",
        lambda check, config: (_ for _ in ()).throw(AssertionError("called")),
    )

    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path), "--dry-run"],
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "シナリオ数: 1 件" in out
    assert "DRY-RUN" in out


def test_dry_run_still_validates_scenario_file(monkeypatch, tmp_path):
    scenario_path, openapi_path, config_path = _write_files(tmp_path, {"not_scenarios": []})
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(config_path), "--dry-run"],
    )
    assert code == 3


def test_dry_run_still_validates_config_file(monkeypatch, tmp_path):
    scenario_path, openapi_path, _ = _write_files(tmp_path, {"scenarios": []})
    bad_config_path = tmp_path / "bad_config.json"
    bad_config_path.write_text("{not valid json", encoding="utf-8")
    code = run_main(
        monkeypatch,
        [str(scenario_path), str(openapi_path), "--base-url", "http://x", "--config", str(bad_config_path), "--dry-run"],
    )
    assert code == 3
