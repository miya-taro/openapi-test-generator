from __future__ import annotations
import json
from pathlib import Path

REQUIRED_DB_KEYS = {"host", "port", "dbname", "user", "password"}


def load_config(config_path: str) -> dict:
    """
    config.json を読み込み db セクションを返す。
    必須キー: host / port / dbname / user / password
    不正な場合は ValueError を raise する。
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"config.json が見つかりません: {config_path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json のパースに失敗しました: {e}") from e

    if "db" not in data:
        raise ValueError('config.json に "db" セクションがありません')

    db = data["db"]
    missing = REQUIRED_DB_KEYS - set(db.keys())
    if missing:
        raise ValueError(f'config.json の db セクションに必須キーが不足しています: {sorted(missing)}')

    return db
