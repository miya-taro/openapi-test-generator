import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_scenario import load_scenarios, resolve_placeholders, resolve_db_check, ScenarioError, DBCheck


def _write_yaml(tmp_path, data: dict) -> Path:
    p = tmp_path / "scenarios.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p


POSTGRES_SCENARIO = {
    "scenarios": [
        {
            "name": "ユーザー作成でusersテーブルに1行増える",
            "request": {"operationId": "createUser", "body": {"name": "太郎", "email": "taro@example.com"}},
            "db_check": {
                "engine": "postgres",
                "table": "users",
                "where": {"email": "taro@example.com"},
                "expect": {"exists": True, "columns": {"name": "太郎"}},
            },
        }
    ]
}


# ---------- load_scenarios: 正常系 ----------


def test_load_postgres_scenario(tmp_path):
    path = _write_yaml(tmp_path, POSTGRES_SCENARIO)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    s = scenarios[0]
    assert s.name == "ユーザー作成でusersテーブルに1行増える"
    assert s.request.operation_id == "createUser"
    assert s.request.body == {"name": "太郎", "email": "taro@example.com"}
    assert s.db_check.engine == "postgres"
    assert s.db_check.table == "users"
    assert s.db_check.where == {"email": "taro@example.com"}
    assert s.db_check.expect == {"exists": True, "columns": {"name": "太郎"}}


def test_load_influxdb_scenario(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "センサーデータ送信でポイントが書き込まれる",
                "request": {"operationId": "postSensorData", "body": {"device_id": "abc123", "temperature": 23.5}},
                "db_check": {
                    "engine": "influxdb",
                    "measurement": "sensor_data",
                    "tags": {"device_id": "abc123"},
                    "time_range": "5m",
                    "expect": {"exists": True, "fields": {"temperature": 23.5}},
                },
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    s = scenarios[0]
    assert s.db_check.engine == "influxdb"
    assert s.db_check.measurement == "sensor_data"
    assert s.db_check.time_range == "5m"


def test_load_scenario_with_path_params(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "ユーザー更新",
                "request": {"operationId": "updateUser", "path_params": {"id": 5}, "body": {"name": "更新後"}},
                "db_check": {"engine": "postgres", "table": "users", "where": {"id": 5}, "expect": {}},
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert scenarios[0].request.path_params == {"id": 5}


def test_load_multiple_scenarios(tmp_path):
    data = {"scenarios": [POSTGRES_SCENARIO["scenarios"][0], POSTGRES_SCENARIO["scenarios"][0]]}
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 2


# ---------- load_scenarios: 異常系 ----------


def test_missing_scenarios_key_raises(tmp_path):
    path = _write_yaml(tmp_path, {"foo": "bar"})
    with pytest.raises(ScenarioError, match="scenarios"):
        load_scenarios(path)


def test_scenarios_not_a_list_raises(tmp_path):
    path = _write_yaml(tmp_path, {"scenarios": "not-a-list"})
    with pytest.raises(ScenarioError):
        load_scenarios(path)


def test_unsupported_engine_raises(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "x",
                "request": {"operationId": "op"},
                "db_check": {"engine": "mongodb", "table": "t", "expect": {}},
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match="mongodb"):
        load_scenarios(path)


def test_missing_required_key_raises(tmp_path):
    data = {"scenarios": [{"name": "x"}]}  # request/db_check なし
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match=r"scenarios\[0\]"):
        load_scenarios(path)


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("scenarios: [unclosed", encoding="utf-8")
    with pytest.raises(ScenarioError):
        load_scenarios(p)


# ---------- resolve_placeholders ----------


def test_resolve_placeholder_simple():
    result = resolve_placeholders("{{response.id}}", {"id": 42})
    assert result == 42


def test_resolve_placeholder_preserves_type():
    result = resolve_placeholders("{{response.temperature}}", {"temperature": 23.5})
    assert result == 23.5
    assert isinstance(result, float)


def test_resolve_placeholder_nested_path():
    result = resolve_placeholders("{{response.user.id}}", {"user": {"id": 7}})
    assert result == 7


def test_resolve_placeholder_missing_key_raises():
    with pytest.raises(ScenarioError):
        resolve_placeholders("{{response.missing}}", {"id": 1})


def test_resolve_non_placeholder_string_unchanged():
    assert resolve_placeholders("plain-value", {"id": 1}) == "plain-value"


def test_resolve_placeholders_in_dict():
    result = resolve_placeholders({"email": "{{response.email}}", "static": "x"}, {"email": "a@b.com"})
    assert result == {"email": "a@b.com", "static": "x"}


def test_resolve_placeholders_non_dict_non_string_passthrough():
    assert resolve_placeholders(42, {}) == 42
    assert resolve_placeholders(None, {}) is None


# ---------- resolve_db_check ----------


def test_resolve_db_check_substitutes_where():
    check = DBCheck(engine="postgres", table="users", where={"id": "{{response.id}}"}, expect={})
    resolved = resolve_db_check(check, {"id": 99})
    assert resolved.where == {"id": 99}
    assert resolved.table == "users"  # 他のフィールドは変更されない


def test_resolve_db_check_substitutes_tags():
    check = DBCheck(engine="influxdb", measurement="m", tags={"device_id": "{{response.deviceId}}"}, expect={})
    resolved = resolve_db_check(check, {"deviceId": "abc"})
    assert resolved.tags == {"device_id": "abc"}


def test_resolve_db_check_no_where_or_tags():
    check = DBCheck(engine="postgres", raw_sql="SELECT 1", expect={})
    resolved = resolve_db_check(check, {})
    assert resolved.where is None
    assert resolved.raw_sql == "SELECT 1"


def test_resolve_db_check_substitutes_expect_columns():
    # README で明言されている「columns にも {{response.xxx}} が使える」の実挙動を担保する
    check = DBCheck(
        engine="postgres", table="order_lines",
        expect={"exists": True, "columns": {"order_id": "{{response.id}}", "quantity": 2}},
    )
    resolved = resolve_db_check(check, {"id": 42})
    assert resolved.expect == {"exists": True, "columns": {"order_id": 42, "quantity": 2}}


def test_resolve_db_check_substitutes_expect_fields():
    check = DBCheck(
        engine="influxdb", measurement="m",
        expect={"exists": True, "fields": {"order_id": "{{response.id}}"}},
    )
    resolved = resolve_db_check(check, {"id": 7})
    assert resolved.expect == {"exists": True, "fields": {"order_id": 7}}


def test_resolve_db_check_expect_without_placeholders_unchanged():
    check = DBCheck(engine="postgres", table="users", expect={"exists": True, "columns": {"name": "太郎"}})
    resolved = resolve_db_check(check, {"id": 1})
    assert resolved.expect == {"exists": True, "columns": {"name": "太郎"}}


def test_resolve_db_check_empty_expect_stays_empty_dict():
    check = DBCheck(engine="postgres", table="users", where={"id": "{{response.id}}"}, expect={})
    resolved = resolve_db_check(check, {"id": 1})
    assert resolved.expect == {}
