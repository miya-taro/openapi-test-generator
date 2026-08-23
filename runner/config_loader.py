from __future__ import annotations
import json
from pathlib import Path

REQUIRED_POSTGRES_KEYS = {"host", "port", "dbname", "user", "password"}
REQUIRED_INFLUXDB_KEYS = {"host", "port", "database"}


def load_config(config_path: str) -> dict:
    """
    config.json を読み込み、生の dict（"postgres" / "influxdb" セクションを含む）を返す。
    実際に使う DB エンジンのセクション検証は get_postgres_config / get_influxdb_config で行う
    （--setup/--teardown は postgres のみ、DBシナリオは使用エンジンのみを要求するため）。
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config.json が見つかりません: {config_path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json のパースに失敗しました: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("config.json の内容が不正です（オブジェクトである必要があります）")

    return data


def get_postgres_config(config: dict) -> dict:
    """config から "postgres" セクションを取り出し、必須キーを検証する。"""
    if "postgres" not in config:
        raise ValueError('config.json に "postgres" セクションがありません')

    postgres = config["postgres"]
    missing = REQUIRED_POSTGRES_KEYS - set(postgres.keys())
    if missing:
        raise ValueError(f'config.json の postgres セクションに必須キーが不足しています: {sorted(missing)}')

    return postgres


def get_influxdb_config(config: dict) -> dict:
    """config から "influxdb" セクションを取り出し、必須キーを検証する。

    username/password は認証なし構成もあるため任意。
    """
    if "influxdb" not in config:
        raise ValueError('config.json に "influxdb" セクションがありません')

    influxdb = config["influxdb"]
    missing = REQUIRED_INFLUXDB_KEYS - set(influxdb.keys())
    if missing:
        raise ValueError(f'config.json の influxdb セクションに必須キーが不足しています: {sorted(missing)}')

    return influxdb
