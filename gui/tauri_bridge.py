#!/usr/bin/env python3
"""Tauri(Rust)側から呼び出す、既存validators.pyの薄いCLIブリッジ。

標準入力からJSON({"command": ..., "args": {...}})を1回だけ受け取り、
結果をJSONで標準出力に1行だけ返す。パス系の引数はWindowsで空白・日本語を含みうるため、
コマンドライン引数ではなく標準入力（UTF-8）でやり取りする。
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validators  # noqa: E402
from workflow.project_store import load_project  # noqa: E402
from workflow.case_master import (  # noqa: E402
    load_case_master,
    save_case_master_reviews,
)

_SAFE_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _load_failed_case_ids(path: str) -> list[str]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(
        isinstance(item, str) and _SAFE_CASE_ID.fullmatch(item) for item in data
    ):
        raise ValueError("失敗ケースID一覧の形式が不正です")
    return list(dict.fromkeys(data))


def _servers_url(path: str) -> str | None:
    """openapi.jsonのservers[0].urlを返す（GUI側のBase URL自動入力用）。"""
    if not path or not Path(path).exists():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        url = data["servers"][0]["url"]
    except (json.JSONDecodeError, OSError, KeyError, IndexError, TypeError):
        return None
    return url if isinstance(url, str) and url else None


def _load_project(path: str) -> dict[str, object]:
    """検証済みのproject.jsonを、GUIで復元できる公開設定だけに変換する。"""
    project = load_project(Path(path))
    return {
        "schemaVersion": project.schema_version,
        "name": project.name,
        "openapiPath": str(project.openapi_path),
        "baseUrl": project.base_url,
        "outputDir": str(project.output_dir),
        "selectedOperations": list(project.selected_operations),
        "setupSqlPath": str(project.setup_sql_path) if project.setup_sql_path else None,
        "teardownSqlPath": str(project.teardown_sql_path) if project.teardown_sql_path else None,
        "dbScenariosPath": str(project.db_scenarios_path) if project.db_scenarios_path else None,
    }


def _dispatch(command: str, args: dict) -> object:
    if command == "servers_url":
        return _servers_url(args["path"])
    if command == "load_project":
        return _load_project(args["path"])
    if command == "load_case_master":
        return load_case_master(args["path"])
    if command == "save_case_master_reviews":
        return save_case_master_reviews(args["path"], args.get("updates"))
    if command == "load_failed_case_ids":
        return _load_failed_case_ids(args["path"])
    if command == "list_operations":
        return validators.list_operations(args["path"])
    if command == "login_operation_hints":
        return validators.login_operation_hints(args["path"], args["operation_id"])
    if command == "health_check":
        return validators.health_check(args["base_url"], args.get("health_path") or "/health")
    if command == "validate_openapi":
        return validators.validate_openapi(args["path"], required=args.get("required", True))
    if command == "validate_db_config":
        return validators.validate_db_config(args["path"], required=args.get("required", True))
    if command == "validate_auth_config":
        return validators.validate_auth_config(args["path"], required=args.get("required", False))
    if command == "validate_sql_file":
        return validators.validate_sql_file(args["path"], required=args.get("required", False))
    if command == "validate_mapping_yaml":
        return validators.validate_mapping_yaml(args["path"], required=args.get("required", True))
    if command == "validate_scenarios_yaml":
        return validators.validate_scenarios_yaml(args["path"], required=args.get("required", True))
    if command == "check_db_connectivity":
        return validators.check_db_connectivity(args["path"])
    raise ValueError(f"unknown command: {command}")


def main() -> int:
    try:
        request = json.loads(sys.stdin.read())
        result = _dispatch(request.get("command", ""), request.get("args", {}))
    except Exception as e:  # ブリッジの境界なので広く捕捉し、失敗もJSONで返す
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
