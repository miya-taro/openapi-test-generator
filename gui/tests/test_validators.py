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
