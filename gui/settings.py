"""GUIの入力値をユーザーホームディレクトリに保存・復元する。"""
from __future__ import annotations
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".openapi_test_gui_settings.json"

DEFAULTS: dict[str, str | bool] = {
    "gen_openapi_path": "",
    "gen_output_dir": "",
    "gen_base_url": "",
    "gen_health_path": "/health",
    "gen_auth_config_path": "",
    "gen_dry_run": False,
    "db_scenario_path": "",
    "db_openapi_path": "",
    "db_config_path": "",
    "db_base_url": "",
    "db_health_path": "/health",
    "db_auth_config_path": "",
    "db_dry_run": False,
}


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**DEFAULTS, **data}
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save_settings(settings: dict) -> None:
    try:
        SETTINGS_PATH.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
