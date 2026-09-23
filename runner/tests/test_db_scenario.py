import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_scenario import (
    load_scenarios, parse_scenarios, resolve_placeholders, resolve_db_check, resolve_invariant_expr,
    ScenarioError, DBCheck,
)


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


# ---------- parse_scenarios（テキスト直接指定版） ----------


def test_parse_scenarios_from_text_equivalent_to_load_scenarios(tmp_path):
    text = yaml.dump(POSTGRES_SCENARIO, allow_unicode=True)
    from_text = parse_scenarios(text)
    path = _write_yaml(tmp_path, POSTGRES_SCENARIO)
    from_file = load_scenarios(path)
    assert len(from_text) == len(from_file) == 1
    assert from_text[0].name == from_file[0].name
    assert from_text[0].db_check.table == from_file[0].db_check.table


def test_db_scenario_case_id_is_stable_and_uses_explicit_id_namespace():
    first = parse_scenarios("""
scenarios:
  - name: get user
    request: {operationId: getUser, path_params: {id: 7}}
    response_check: {expect: {status: 200}}
""")[0]
    reordered = parse_scenarios("""
scenarios:
  - request: {path_params: {id: 7}, operationId: getUser}
    response_check: {expect: {status: 200}}
    name: get user
""")[0]
    explicit = parse_scenarios("""
scenarios:
  - id: get-user
    name: get user
    request: {operationId: getUser}
    response_check: {expect: {status: 200}}
""")[0]

    assert first.case_id == reordered.case_id
    assert first.case_id.startswith("DB-")
    assert explicit.case_id == "DB-get-user"


def test_auth_profile_is_part_of_scenario_and_stable_case_definition():
    scenario = parse_scenarios("""
scenarios:
  - name: read-only user cannot update another user's record
    auth_profile: read_only
    request: {operationId: updateUser, path_params: {id: 7}}
    response_check: {expect: {status: 403}}
""")[0]

    assert scenario.auth_profile == "read_only"
    assert scenario.case_definition()["authProfile"] == "read_only"


@pytest.mark.parametrize("profile", ["", "bad profile", "../reader"])
def test_invalid_auth_profile_is_rejected(profile):
    text = f"""
scenarios:
  - name: invalid auth profile
    auth_profile: {profile!r}
    request: {{operationId: getUser}}
    response_check: {{expect: {{status: 403}}}}
"""
    with pytest.raises(ScenarioError, match="auth_profile"):
        parse_scenarios(text)


def test_duplicate_db_case_ids_are_rejected_at_parse_time():
    with pytest.raises(ScenarioError, match="試験IDが重複"):
        parse_scenarios("""
scenarios:
  - id: same
    name: one
    request: {operationId: getUser}
    response_check: {expect: {status: 200}}
  - id: same
    name: two
    request: {operationId: getUser}
    response_check: {expect: {status: 200}}
""")


def test_parse_scenarios_invalid_yaml_raises_scenario_error():
    with pytest.raises(ScenarioError, match="パース"):
        parse_scenarios("scenarios: [unterminated")


def test_parse_scenarios_missing_scenarios_key_raises():
    with pytest.raises(ScenarioError, match="scenarios"):
        parse_scenarios("foo: bar")


def test_load_scenarios_missing_file_raises_scenario_error(tmp_path):
    with pytest.raises(ScenarioError, match="読み込み"):
        load_scenarios(tmp_path / "does_not_exist.yaml")


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
    assert scenarios[0].case_id != scenarios[1].case_id


# ---------- load_scenarios: defaults/list 形式（engineの重複記述を省略する） ----------


def test_defaults_engine_applied_when_scenario_omits_engine(tmp_path):
    data = {
        "scenarios": {
            "defaults": {"engine": "postgres"},
            "list": [
                {
                    "name": "ユーザー作成",
                    "request": {"operationId": "createUser", "body": {"name": "太郎"}},
                    "db_check": {"table": "users", "where": {"name": "太郎"}, "expect": {"exists": True}},
                }
            ],
        }
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    assert scenarios[0].db_check.engine == "postgres"


def test_scenario_level_engine_overrides_defaults(tmp_path):
    data = {
        "scenarios": {
            "defaults": {"engine": "postgres"},
            "list": [
                {
                    "name": "センサーデータ",
                    "request": {"operationId": "postSensorData", "body": {}},
                    "db_check": {"engine": "influxdb", "measurement": "m", "expect": {"exists": True}},
                }
            ],
        }
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert scenarios[0].db_check.engine == "influxdb"


def test_multiple_scenarios_share_defaults(tmp_path):
    data = {
        "scenarios": {
            "defaults": {"engine": "postgres"},
            "list": [
                {
                    "name": "A",
                    "request": {"operationId": "createUser", "body": {}},
                    "db_check": {"table": "users", "expect": {"exists": True}},
                },
                {
                    "name": "B",
                    "request": {"operationId": "createOrder", "body": {}},
                    "db_check": {"table": "orders", "expect": {"exists": True}},
                },
            ],
        }
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 2
    assert all(s.db_check.engine == "postgres" for s in scenarios)


def test_defaults_missing_engine_and_scenario_omits_engine_raises(tmp_path):
    data = {
        "scenarios": {
            "defaults": {},
            "list": [
                {
                    "name": "x",
                    "request": {"operationId": "op", "body": {}},
                    "db_check": {"table": "t", "expect": {}},
                }
            ],
        }
    }
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match="engine"):
        load_scenarios(path)


def test_scenarios_dict_without_list_key_raises(tmp_path):
    data = {"scenarios": {"defaults": {"engine": "postgres"}}}
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match="list"):
        load_scenarios(path)


def test_scenarios_defaults_not_an_object_raises(tmp_path):
    data = {"scenarios": {"defaults": "not-an-object", "list": []}}
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match="defaults"):
        load_scenarios(path)


def test_old_list_format_still_works_without_defaults_key(tmp_path):
    # 旧形式（scenarios が直接リスト）は defaults なしでも従来通り動作する（後方互換）
    path = _write_yaml(tmp_path, POSTGRES_SCENARIO)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    assert scenarios[0].db_check.engine == "postgres"


# ---------- load_scenarios: response_check（APIレスポンス自体の検証） ----------


def test_load_scenario_with_response_check_only(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "最大値の注文を取得できる",
                "request": {"operationId": "getOrder", "path_params": {"id": 999}},
                "response_check": {
                    "expect": {"status": 200, "body": {"price": 99999999.99}}
                },
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    assert len(scenarios) == 1
    s = scenarios[0]
    assert s.db_check is None
    assert s.response_check.expect_status == 200
    assert s.response_check.expect_body == {"price": 99999999.99}


def test_load_scenario_with_both_db_check_and_response_check(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "作成もDBもレスポンスも確認",
                "request": {"operationId": "createUser", "body": {}},
                "db_check": {"engine": "postgres", "table": "users", "expect": {}},
                "response_check": {"expect": {"status": 201}},
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    s = scenarios[0]
    assert s.db_check is not None
    assert s.db_check.engine == "postgres"
    assert s.response_check is not None
    assert s.response_check.expect_status == 201


def test_scenario_without_db_check_or_response_check_raises(tmp_path):
    data = {
        "scenarios": [
            {"name": "何も確認しない", "request": {"operationId": "getOrder", "path_params": {"id": 1}}}
        ]
    }
    path = _write_yaml(tmp_path, data)
    with pytest.raises(ScenarioError, match="db_check.*response_check|response_check.*db_check"):
        load_scenarios(path)


def test_response_check_without_expect_key_defaults_to_empty(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "expectなし",
                "request": {"operationId": "getOrder", "path_params": {"id": 1}},
                "response_check": {},
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    s = scenarios[0]
    assert s.response_check.expect_status is None
    assert s.response_check.expect_body == {}


def test_response_check_body_only_no_status(tmp_path):
    data = {
        "scenarios": [
            {
                "name": "bodyだけ確認",
                "request": {"operationId": "getOrder", "path_params": {"id": 1}},
                "response_check": {"expect": {"body": {"status": "pending"}}},
            }
        ]
    }
    path = _write_yaml(tmp_path, data)
    scenarios = load_scenarios(path)
    s = scenarios[0]
    assert s.response_check.expect_status is None
    assert s.response_check.expect_body == {"status": "pending"}


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


# ---------- invariants（不変条件） ----------


def test_resolve_invariant_expr_substitutes_given_and_response():
    resolved = resolve_invariant_expr(
        "{{db.stock}} == {{given.product_a.stock}} - {{response.qty}}",
        {"qty": 1},
        {"product_a": {"stock": 10}},
    )
    assert resolved == "{{db.stock}} == 10 - 1"


def test_resolve_invariant_expr_leaves_db_placeholder_untouched():
    resolved = resolve_invariant_expr("{{db.stock}} >= 0", {}, {})
    assert resolved == "{{db.stock}} >= 0"


def test_resolve_invariant_expr_missing_given_key_raises():
    with pytest.raises(ScenarioError):
        resolve_invariant_expr("{{given.missing.id}} == 1", {}, {"product_a": {"id": 1}})


def test_resolve_invariant_expr_unknown_namespace_raises():
    with pytest.raises(ScenarioError, match="名前空間"):
        resolve_invariant_expr("{{unknown.x}} == 1", {}, {})


def test_resolve_db_check_resolves_invariants_list():
    check = DBCheck(
        engine="postgres", table="products", where={"id": "{{given.product_a.id}}"},
        invariants=["{{db.stock}} == {{given.product_a.stock}} - 1"],
    )
    resolved = resolve_db_check(check, {}, {"product_a": {"id": 5, "stock": 10}})
    assert resolved.invariants == ["{{db.stock}} == 10 - 1"]
    assert resolved.where == {"id": 5}


def test_resolve_db_check_no_invariants_stays_empty_list():
    check = DBCheck(engine="postgres", table="users", expect={})
    resolved = resolve_db_check(check, {})
    assert resolved.invariants == []


def test_parse_scenario_with_invariants():
    data = {
        "scenarios": [{
            "name": "在庫が減る",
            "request": {"operationId": "createOrder"},
            "db_check": {
                "engine": "postgres", "table": "products",
                "invariants": ["{{db.stock}} >= 0", "{{db.stock}} == {{given.product_a.stock}} - 1"],
            },
        }]
    }
    scenarios = parse_scenarios(yaml.dump(data, allow_unicode=True))
    assert scenarios[0].db_check.invariants == [
        "{{db.stock}} >= 0", "{{db.stock}} == {{given.product_a.stock}} - 1",
    ]


def test_parse_scenario_without_invariants_defaults_to_empty_list():
    scenarios = parse_scenarios(yaml.dump(POSTGRES_SCENARIO, allow_unicode=True))
    assert scenarios[0].db_check.invariants == []


def test_parse_scenario_invariants_must_be_list_of_strings():
    data = {
        "scenarios": [{
            "name": "x",
            "request": {"operationId": "createOrder"},
            "db_check": {"engine": "postgres", "table": "t", "invariants": [123]},
        }]
    }
    with pytest.raises(ScenarioError, match="invariants"):
        parse_scenarios(yaml.dump(data, allow_unicode=True))


# ---------- given（factory前提データ）プレースホルダ ----------


def test_resolve_placeholder_given_namespace():
    result = resolve_placeholders("{{given.product_a.id}}", {}, {"product_a": {"id": 5, "stock": 10}})
    assert result == 5


def test_resolve_placeholder_given_missing_key_raises():
    with pytest.raises(ScenarioError):
        resolve_placeholders("{{given.product_a.id}}", {}, {"other": {"id": 1}})


def test_resolve_placeholder_given_without_given_arg_raises():
    # given を渡さない（Noneのまま）場合でも、response.xxx の解決には影響しない後方互換性を保つ
    with pytest.raises(ScenarioError):
        resolve_placeholders("{{given.product_a.id}}", {})


def test_resolve_placeholder_unknown_namespace_raises():
    with pytest.raises(ScenarioError, match="名前空間"):
        resolve_placeholders("{{unknown.id}}", {"id": 1})


def test_resolve_placeholders_response_and_given_together_in_dict():
    result = resolve_placeholders(
        {"user_id": "{{response.id}}", "product_id": "{{given.product_a.id}}"},
        {"id": 42},
        {"product_a": {"id": 7}},
    )
    assert result == {"user_id": 42, "product_id": 7}


def test_resolve_db_check_where_with_given_namespace():
    check = DBCheck(engine="postgres", table="products", where={"id": "{{given.product_a.id}}"}, expect={})
    resolved = resolve_db_check(check, {}, {"product_a": {"id": 5}})
    assert resolved.where == {"id": 5}


# ---------- given（factory前提データ）のYAML解析 ----------


GIVEN_SCENARIO = {
    "scenarios": [
        {
            "name": "在庫がある商品を注文すると在庫が減る",
            "given": [
                {"table": "products", "as": "product_a", "fields": {"name": "商品A", "stock": 10}},
            ],
            "request": {
                "operationId": "createOrder",
                "body": {"product_id": "{{given.product_a.id}}", "qty": 1},
            },
            "db_check": {
                "engine": "postgres", "table": "products",
                "where": {"id": "{{given.product_a.id}}"}, "expect": {"stock": 9},
            },
        }
    ]
}


def test_parse_scenario_with_given_items():
    scenarios = parse_scenarios(yaml.dump(GIVEN_SCENARIO, allow_unicode=True))
    assert len(scenarios) == 1
    given = scenarios[0].given
    assert len(given) == 1
    assert given[0].table == "products"
    assert given[0].as_name == "product_a"
    assert given[0].fields == {"name": "商品A", "stock": 10}


def test_parse_scenario_without_given_defaults_to_empty_list():
    scenarios = parse_scenarios(yaml.dump(POSTGRES_SCENARIO, allow_unicode=True))
    assert scenarios[0].given == []


def test_parse_scenario_given_missing_table_raises():
    data = {
        "scenarios": [{
            "name": "x", "given": [{"as": "product_a", "fields": {}}],
            "request": {"operationId": "createOrder"},
            "db_check": {"engine": "postgres", "table": "t", "expect": {}},
        }]
    }
    with pytest.raises(ScenarioError, match="given\\[0\\]"):
        parse_scenarios(yaml.dump(data, allow_unicode=True))


def test_parse_scenario_given_missing_as_raises():
    data = {
        "scenarios": [{
            "name": "x", "given": [{"table": "products", "fields": {}}],
            "request": {"operationId": "createOrder"},
            "db_check": {"engine": "postgres", "table": "t", "expect": {}},
        }]
    }
    with pytest.raises(ScenarioError, match="given\\[0\\]"):
        parse_scenarios(yaml.dump(data, allow_unicode=True))


def test_parse_scenario_given_fields_defaults_to_empty_dict():
    data = {
        "scenarios": [{
            "name": "x", "given": [{"table": "products", "as": "product_a"}],
            "request": {"operationId": "createOrder"},
            "db_check": {"engine": "postgres", "table": "t", "expect": {}},
        }]
    }
    scenarios = parse_scenarios(yaml.dump(data, allow_unicode=True))
    assert scenarios[0].given[0].fields == {}
