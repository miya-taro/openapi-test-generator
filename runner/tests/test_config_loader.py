import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import load_config, get_postgres_config, get_influxdb_config

VALID_POSTGRES = {
    "host": "192.168.1.100",
    "port": 5432,
    "dbname": "mydb",
    "user": "testuser",
    "password": "testpass",
}

VALID_INFLUXDB = {
    "host": "192.168.1.100",
    "port": 8086,
    "database": "metrics",
    "username": "testuser",
    "password": "testpass",
}

VALID_CONFIG = {"postgres": VALID_POSTGRES, "influxdb": VALID_INFLUXDB}


def write_config(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# ---------- load_config: 正常系 ----------


def test_load_config_returns_whole_dict(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG)
    config = load_config(path)
    assert config["postgres"]["host"] == "192.168.1.100"
    assert config["influxdb"]["database"] == "metrics"


def test_load_config_ignores_unknown_top_level_keys(tmp_path):
    data = {**VALID_CONFIG, "other_key": "should be ignored elsewhere but kept as-is here"}
    path = write_config(tmp_path, data)
    config = load_config(path)
    assert config["other_key"] == "should be ignored elsewhere but kept as-is here"


# ---------- load_config: 異常系 ----------


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="config.json が見つかりません"):
        load_config(str(tmp_path / "nonexistent.json"))


def test_invalid_json_raises_value_error(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="パース"):
        load_config(str(p))


def test_non_object_json_raises_value_error(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(str(p))


# ---------- get_postgres_config ----------


def test_get_postgres_config_valid():
    pg = get_postgres_config(VALID_CONFIG)
    assert pg == VALID_POSTGRES


def test_get_postgres_config_missing_section_raises():
    with pytest.raises(ValueError, match='"postgres"'):
        get_postgres_config({"influxdb": VALID_INFLUXDB})


def test_get_postgres_config_missing_host_raises():
    config = {"postgres": {k: v for k, v in VALID_POSTGRES.items() if k != "host"}}
    with pytest.raises(ValueError, match="host"):
        get_postgres_config(config)


def test_get_postgres_config_missing_password_raises():
    config = {"postgres": {k: v for k, v in VALID_POSTGRES.items() if k != "password"}}
    with pytest.raises(ValueError, match="password"):
        get_postgres_config(config)


def test_get_postgres_config_missing_multiple_keys_raises():
    with pytest.raises(ValueError):
        get_postgres_config({"postgres": {"host": "localhost"}})


# ---------- get_influxdb_config ----------


def test_get_influxdb_config_valid():
    influx = get_influxdb_config(VALID_CONFIG)
    assert influx == VALID_INFLUXDB


def test_get_influxdb_config_missing_section_raises():
    with pytest.raises(ValueError, match='"influxdb"'):
        get_influxdb_config({"postgres": VALID_POSTGRES})


def test_get_influxdb_config_missing_database_raises():
    config = {"influxdb": {k: v for k, v in VALID_INFLUXDB.items() if k != "database"}}
    with pytest.raises(ValueError, match="database"):
        get_influxdb_config(config)


def test_get_influxdb_config_username_password_optional():
    # 認証なし構成もあるため username/password は必須キーに含まれない
    config = {"influxdb": {"host": "h", "port": 8086, "database": "d"}}
    influx = get_influxdb_config(config)
    assert influx["database"] == "d"
