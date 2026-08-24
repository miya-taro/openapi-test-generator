import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import validators


# --- validate_openapi ---


def test_validate_openapi_blank_optional_returns_placeholder():
    assert validators.validate_openapi("", required=False) == "（未入力・任意）"


def test_validate_openapi_blank_required_returns_ng():
    assert validators.validate_openapi("", required=True).startswith("NG")


def test_validate_openapi_missing_file(tmp_path):
    result = validators.validate_openapi(str(tmp_path / "missing.json"))
    assert result.startswith("NG")
    assert "見つかりません" in result


def test_validate_openapi_valid_file_reports_operation_count(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "paths": {
            "/users": {"get": {"operationId": "listUsers"}, "post": {"operationId": "createUser"}},
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    result = validators.validate_openapi(str(path))
    assert result.startswith("OK")
    assert "2" in result


def test_validate_openapi_rejects_v2(tmp_path):
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    result = validators.validate_openapi(str(path))
    assert result.startswith("NG")


# --- list_operations ---


def test_list_operations_blank_returns_empty():
    assert validators.list_operations("") == []


def test_list_operations_missing_file_returns_empty(tmp_path):
    assert validators.list_operations(str(tmp_path / "missing.json")) == []


def test_list_operations_returns_method_path_and_operation_id(tmp_path):
    doc = {
        "openapi": "3.0.3",
        "paths": {
            "/users": {"get": {"operationId": "listUsers"}, "post": {"operationId": "createUser"}},
            "/users/{id}": {"delete": {"operationId": "deleteUser"}},
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    ops = validators.list_operations(str(path))

    assert {o["operationId"] for o in ops} == {"listUsers", "createUser", "deleteUser"}
    listed = next(o for o in ops if o["operationId"] == "listUsers")
    assert listed == {"operationId": "listUsers", "method": "GET", "path": "/users"}


def test_list_operations_skips_operations_without_operation_id(tmp_path):
    doc = {"openapi": "3.0.3", "paths": {"/health": {"get": {}}}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    assert validators.list_operations(str(path)) == []


# --- login_operation_hints ---


def test_login_operation_hints_blank_returns_none():
    assert validators.login_operation_hints("", "login") == {"body": None, "token_path": None}


def test_login_operation_hints_missing_operation_returns_none(tmp_path):
    doc = {"openapi": "3.0.3", "paths": {"/users": {"get": {"operationId": "listUsers"}}}}
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert validators.login_operation_hints(str(path), "login") == {"body": None, "token_path": None}


def test_login_operation_hints_builds_body_from_required_properties(tmp_path):
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
                                    "required": ["email", "password"],
                                    "properties": {
                                        "email": {"type": "string"},
                                        "password": {"type": "string"},
                                        "rememberMe": {"type": "boolean"},
                                    },
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

    hints = validators.login_operation_hints(str(path), "login")

    # required でない rememberMe は含まれない
    assert hints["body"] == {"email": "email", "password": "password"}
    assert hints["token_path"] is None


def test_login_operation_hints_prefers_example_and_guesses_token_path(tmp_path):
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
                                    "properties": {"email": {"type": "string", "example": "a@example.com"}},
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"access_token": {"type": "string"}},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        },
    }
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(doc), encoding="utf-8")

    hints = validators.login_operation_hints(str(path), "login")

    assert hints["body"] == {"email": "a@example.com"}
    assert hints["token_path"] == "access_token"


# --- health_check ---


def test_health_check_unreachable_host_returns_false():
    assert validators.health_check("http://127.0.0.1:1", "/health") is False


# --- validate_db_config ---


def test_validate_db_config_valid_postgres(tmp_path):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    result = validators.validate_db_config(str(path))
    assert result.startswith("OK")
    assert "postgres: OK" in result


def test_validate_db_config_missing_required_key(tmp_path):
    cfg = {"postgres": {"host": "h", "port": 5432}}  # dbname/user/password 不足
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    result = validators.validate_db_config(str(path))
    assert "postgres: NG" in result


def test_validate_db_config_no_known_sections(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    result = validators.validate_db_config(str(path))
    assert result.startswith("NG")


def test_validate_db_config_invalid_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    result = validators.validate_db_config(str(path))
    assert result.startswith("NG")


# --- validate_auth_config ---


def test_validate_auth_config_blank_is_optional_by_default():
    assert validators.validate_auth_config("") == "（未入力・任意）"


def test_validate_auth_config_valid(tmp_path):
    path = tmp_path / "auth.yaml"
    path.write_text("login_url: /login\nmethod: POST\n", encoding="utf-8")
    result = validators.validate_auth_config(str(path))
    assert result.startswith("OK")
    assert "/login" in result


def test_validate_auth_config_missing_required_key(tmp_path):
    path = tmp_path / "auth.yaml"
    path.write_text("login_url: /login\n", encoding="utf-8")  # methodが無い
    result = validators.validate_auth_config(str(path))
    assert result.startswith("NG")


# --- validate_scenarios_yaml ---


def test_validate_scenarios_yaml_valid(tmp_path):
    content = (
        "scenarios:\n"
        "  - name: test\n"
        "    request:\n"
        "      operationId: op1\n"
        "    response_check:\n"
        "      expect: {}\n"
    )
    path = tmp_path / "scenarios.yaml"
    path.write_text(content, encoding="utf-8")
    result = validators.validate_scenarios_yaml(str(path))
    assert result.startswith("OK")
    assert "1件" in result


def test_validate_scenarios_yaml_missing_scenarios_key(tmp_path):
    path = tmp_path / "scenarios.yaml"
    path.write_text("foo: bar\n", encoding="utf-8")
    result = validators.validate_scenarios_yaml(str(path))
    assert result.startswith("NG")


# --- validate_mapping_yaml ---


def test_validate_mapping_yaml_valid(tmp_path):
    content = "operations:\n  createUser:\n    engine: postgres\n    table: users\n"
    path = tmp_path / "mapping.yaml"
    path.write_text(content, encoding="utf-8")
    result = validators.validate_mapping_yaml(str(path))
    assert result.startswith("OK")
    assert "1件" in result


def test_validate_mapping_yaml_missing_operations_key(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text("foo: bar\n", encoding="utf-8")
    result = validators.validate_mapping_yaml(str(path))
    assert result.startswith("NG")


# --- validate_mapping_yaml_text / validate_scenarios_yaml_text ---


def test_validate_mapping_yaml_text_empty():
    assert validators.validate_mapping_yaml_text("") == "（空です）"
    assert validators.validate_mapping_yaml_text("   \n") == "（空です）"


def test_validate_mapping_yaml_text_valid():
    result = validators.validate_mapping_yaml_text("operations:\n  createUser:\n    table: users\n")
    assert result.startswith("OK")
    assert "1件" in result


def test_validate_mapping_yaml_text_invalid_yaml():
    result = validators.validate_mapping_yaml_text("operations: [unterminated")
    assert result.startswith("NG")


def test_validate_mapping_yaml_text_missing_operations_key():
    result = validators.validate_mapping_yaml_text("foo: bar")
    assert result.startswith("NG")


def test_validate_mapping_yaml_path_delegates_to_text_variant(tmp_path):
    path = tmp_path / "mapping.yaml"
    path.write_text("operations:\n  a: {}\n  b: {}\n", encoding="utf-8")
    assert validators.validate_mapping_yaml(str(path)) == validators.validate_mapping_yaml_text(
        path.read_text(encoding="utf-8")
    )


def test_validate_scenarios_yaml_text_empty():
    assert validators.validate_scenarios_yaml_text("") == "（空です）"


def test_validate_scenarios_yaml_text_valid():
    text = (
        "scenarios:\n"
        "  - name: test\n"
        "    request:\n"
        "      operationId: op1\n"
        "    response_check:\n"
        "      expect: {}\n"
    )
    result = validators.validate_scenarios_yaml_text(text)
    assert result.startswith("OK")
    assert "1件" in result


def test_validate_scenarios_yaml_text_invalid():
    result = validators.validate_scenarios_yaml_text("foo: bar")
    assert result.startswith("NG")


# --- check_sql_syntax ---


def test_check_sql_syntax_empty_text():
    assert validators.check_sql_syntax("", "some/config.json") == "（空です）"


def test_check_sql_syntax_blank_config_path():
    result = validators.check_sql_syntax("SELECT 1;", "")
    assert "未入力" in result


def test_check_sql_syntax_missing_config_file(tmp_path):
    result = validators.check_sql_syntax("SELECT 1;", str(tmp_path / "missing.json"))
    assert result.startswith("NG")
    assert "見つかりません" in result


def test_check_sql_syntax_success(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def rollback(self):
            pass

        def close(self):
            pass

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())

    result = validators.check_sql_syntax("INSERT INTO users (id) VALUES (1);", str(path))
    assert result.startswith("OK")


def test_check_sql_syntax_execution_error_still_rolls_back(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    rollback_calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            raise RuntimeError("syntax error at or near \"BOGUS\"")

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def rollback(self):
            rollback_calls.append(1)

        def close(self):
            pass

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())

    result = validators.check_sql_syntax("BOGUS SQL;", str(path))
    assert result.startswith("NG")
    assert "syntax error" in result
    assert rollback_calls == [1]  # エラー時もrollbackされていること


def test_check_sql_syntax_connect_failure(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    import psycopg2

    def fake_connect(**kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    result = validators.check_sql_syntax("SELECT 1;", str(path))
    assert result.startswith("NG")
    assert "接続に失敗" in result


# --- execute_sql ---


def test_execute_sql_empty_text():
    assert validators.execute_sql("", "some/config.json") == "（空です）"


def test_execute_sql_blank_config_path():
    result = validators.execute_sql("TRUNCATE TABLE users;", "")
    assert "未入力" in result


def test_execute_sql_success_commits(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            calls.append(("execute", sql))

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            calls.append(("commit",))

        def rollback(self):
            calls.append(("rollback",))

        def close(self):
            calls.append(("close",))

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())

    result = validators.execute_sql("INSERT INTO users (id) VALUES (1);", str(path))

    assert result == "OK: DBに反映しました"
    assert ("commit",) in calls
    assert ("rollback",) not in calls  # 成功時はrollbackしないこと


def test_execute_sql_error_rolls_back_not_commits(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            raise RuntimeError("constraint violation")

    class FakeConn:
        def cursor(self):
            return FakeCursor()

        def commit(self):
            calls.append("commit")

        def rollback(self):
            calls.append("rollback")

        def close(self):
            pass

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())

    result = validators.execute_sql("BOGUS;", str(path))

    assert result.startswith("NG")
    assert "constraint violation" in result
    assert "commit" not in calls
    assert "rollback" in calls


def test_execute_sql_connect_failure(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    import psycopg2

    def fake_connect(**kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    result = validators.execute_sql("SELECT 1;", str(path))
    assert result.startswith("NG")
    assert "接続に失敗" in result


# --- validate_sql_file ---


def test_validate_sql_file_blank_optional():
    assert validators.validate_sql_file("") == "（未入力・任意）"


def test_validate_sql_file_valid(tmp_path):
    path = tmp_path / "setup.sql"
    path.write_text("INSERT INTO users VALUES (1);\nINSERT INTO orders VALUES (1);\n", encoding="utf-8")
    result = validators.validate_sql_file(str(path))
    assert result.startswith("OK")
    assert "2" in result


# --- check_db_connectivity ---


def test_check_db_connectivity_blank_path():
    assert validators.check_db_connectivity("") == "（未入力）"


def test_check_db_connectivity_missing_file(tmp_path):
    result = validators.check_db_connectivity(str(tmp_path / "missing.json"))
    assert result.startswith("NG")


def test_check_db_connectivity_no_known_sections(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    result = validators.check_db_connectivity(str(path))
    assert result.startswith("NG")


def test_check_db_connectivity_postgres_success(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    class FakeConn:
        def close(self):
            pass

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())

    result = validators.check_db_connectivity(str(path))
    assert result == "postgres: OK（接続できました）"


def test_check_db_connectivity_postgres_failure(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    import psycopg2

    def fake_connect(**kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(psycopg2, "connect", fake_connect)

    result = validators.check_db_connectivity(str(path))
    assert "postgres: NG" in result
    assert "connection refused" in result


def test_check_db_connectivity_reports_both_engines(tmp_path, monkeypatch):
    cfg = {
        "postgres": {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"},
        "influxdb": {"host": "ih", "port": 8086, "database": "idb"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    class FakeConn:
        def close(self):
            pass

    class FakeInfluxClient:
        def __init__(self, **kwargs):
            pass

        def ping(self):
            pass

        def close(self):
            pass

    import psycopg2
    import influxdb
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: FakeConn())
    monkeypatch.setattr(influxdb, "InfluxDBClient", FakeInfluxClient)

    result = validators.check_db_connectivity(str(path))
    assert "postgres: OK" in result
    assert "influxdb: OK" in result


def test_check_db_connectivity_postgres_missing_required_key_does_not_attempt_connect(tmp_path, monkeypatch):
    cfg = {"postgres": {"host": "h"}}  # 必須キー不足
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    called = []
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda **kwargs: called.append(1))

    result = validators.check_db_connectivity(str(path))
    assert "postgres: NG" in result
    assert called == []


def test_validate_sql_file_empty(tmp_path):
    path = tmp_path / "setup.sql"
    path.write_text("", encoding="utf-8")
    result = validators.validate_sql_file(str(path))
    assert result.startswith("NG")
