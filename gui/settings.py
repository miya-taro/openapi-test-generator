"""GUIの入力値をユーザーホームディレクトリに保存・復元する。"""
from __future__ import annotations
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".openapi_test_gui_settings.json"

DEFAULTS: dict[str, str | bool] = {
    "shared_openapi_path": "",
    "shared_config_path": "",
    "gen_output_dir": "",
    "gen_base_url": "",
    "gen_health_path": "/health",
    "gen_health_check_enabled": False,
    "gen_auth_config_path": "",
    "gen_dry_run": False,
    "gen_setup_path": "",
    "gen_teardown_path": "",
    "gen_full_body": False,
    "gen_fail_fast": False,
    "db_scenario_path": "",
    "db_base_url": "",
    "db_health_path": "/health",
    "db_health_check_enabled": False,
    "db_auth_config_path": "",
    "db_dry_run": False,
    "db_report_dir": "",
    "cfg_output_path": "",
    "cfg_pg_enabled": True,
    "cfg_pg_host": "localhost",
    "cfg_pg_port": "5432",
    "cfg_pg_dbname": "",
    "cfg_pg_user": "",
    "cfg_influx_enabled": False,
    "cfg_influx_host": "localhost",
    "cfg_influx_port": "8086",
    "cfg_influx_database": "",
    "cfg_influx_username": "",
    "authb_output_path": "",
    "authb_login_url": "",
    "authb_method": "POST",
    "authb_body": "",
    "authb_token_path": "access_token",
    "authb_header_name": "Authorization",
    "authb_header_format": "Bearer {token}",
    "mapgen_schema": "public",
    "mapgen_output_dir": "",
    "sqlgen_schema": "public",
    "sqlgen_tables": "",
    "sqlgen_output_dir": "",
    "scengen_mapping_path": "",
    "scengen_output_dir": "",
}


# 過去バージョンではopenapi.json/DB接続設定の入力欄がタブごとに独立していた名残。
# 1箇所に統合した際、既存ユーザーの設定ファイルにこれらの値が残っていれば
# shared_*_pathへ引き継ぐ（_migrate_legacy_shared_paths参照）。
_LEGACY_SHARED_PATH_KEYS = {
    "shared_openapi_path": ("gen_openapi_path", "mapgen_openapi_path", "scengen_openapi_path", "db_openapi_path"),
    "shared_config_path": ("gen_config_path", "mapgen_config_path", "sqlgen_config_path", "db_config_path"),
}


def _migrate_legacy_shared_paths(merged: dict) -> dict:
    for shared_key, legacy_keys in _LEGACY_SHARED_PATH_KEYS.items():
        if merged.get(shared_key):
            continue
        for key in legacy_keys:
            value = merged.get(key)
            if value:
                merged[shared_key] = value
                break
    return merged


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _migrate_legacy_shared_paths({**DEFAULTS, **data})
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
