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
    "gen_config_path": "",
    "gen_setup_path": "",
    "gen_teardown_path": "",
    "gen_full_body": False,
    "gen_fail_fast": False,
    "db_scenario_path": "",
    "db_openapi_path": "",
    "db_config_path": "",
    "db_base_url": "",
    "db_health_path": "/health",
    "db_auth_config_path": "",
    "db_dry_run": False,
    "mapgen_openapi_path": "",
    "mapgen_config_path": "",
    "mapgen_schema": "public",
    "mapgen_output_dir": "",
    "sqlgen_config_path": "",
    "sqlgen_schema": "public",
    "sqlgen_tables": "",
    "sqlgen_output_dir": "",
    "scengen_openapi_path": "",
    "scengen_mapping_path": "",
    "scengen_output_dir": "",
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
