import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from config_loader import load_config

VALID_CONFIG = {
    "db": {
        "host": "192.168.1.100",
        "port": 5432,
        "dbname": "mydb",
        "user": "testuser",
        "password": "testpass",
    }
}


def write_config(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


# ---------- 正常系 ----------

def test_load_valid_config(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG)
    db = load_config(path)
    assert db["host"] == "192.168.1.100"
    assert db["port"] == 5432
    assert db["dbname"] == "mydb"
    assert db["user"] == "testuser"
    assert db["password"] == "testpass"


def test_load_returns_only_db_section(tmp_path):
    data = {**VALID_CONFIG, "other_key": "should be ignored"}
    path = write_config(tmp_path, data)
    db = load_config(path)
    assert "other_key" not in db


# ---------- 異常系: ファイルなし ----------

def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError, match="config.json が見つかりません"):
        load_config(str(tmp_path / "nonexistent.json"))


# ---------- 異常系: 必須キー不足 ----------

def test_missing_host_raises_value_error(tmp_path):
    config = {
        "db": {k: v for k, v in VALID_CONFIG["db"].items() if k != "host"}
    }
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match="host"):
        load_config(path)


def test_missing_password_raises_value_error(tmp_path):
    config = {
        "db": {k: v for k, v in VALID_CONFIG["db"].items() if k != "password"}
    }
    path = write_config(tmp_path, config)
    with pytest.raises(ValueError, match="password"):
        load_config(path)


def test_missing_multiple_keys_raises_value_error(tmp_path):
    path = write_config(tmp_path, {"db": {"host": "localhost"}})
    with pytest.raises(ValueError):
        load_config(path)


# ---------- 異常系: db セクションなし ----------

def test_missing_db_section_raises_value_error(tmp_path):
    path = write_config(tmp_path, {"other": "value"})
    with pytest.raises(ValueError, match='"db"'):
        load_config(path)


# ---------- 異常系: JSON パースエラー ----------

def test_invalid_json_raises_value_error(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="パース"):
        load_config(str(p))
