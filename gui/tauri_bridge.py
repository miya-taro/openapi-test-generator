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

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import validators  # noqa: E402
from openapi_editor import create_operation_document, load_operation_body_contract, save_operation_body_contract  # noqa: E402
from workflow.project_store import load_project  # noqa: E402
from workflow.case_master import (  # noqa: E402
    load_case_master,
    save_case_master_reviews,
)
from src.parser import parse_openapi  # noqa: E402
from db_scenario import parse_scenarios  # noqa: E402

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


def _json_media_content(content: object) -> dict:
    if not isinstance(content, dict):
        return {}
    json_content = content.get("application/json")
    if isinstance(json_content, dict):
        return json_content
    for media_type, value in content.items():
        normalized = str(media_type).split(";", 1)[0].strip().lower()
        if normalized.endswith("+json") and isinstance(value, dict):
            return value
    return {}


def _list_db_scenario_operations(path: str) -> list[dict[str, object]]:
    """Return operation details needed by the DB scenario editor."""
    openapi = parse_openapi(path)
    operations: list[dict[str, object]] = []
    for route, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            parameters_by_key: dict[tuple[str, str], dict] = {}
            for parameter in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
                if isinstance(parameter, dict) and parameter.get("name") and parameter.get("in"):
                    parameters_by_key[(parameter["in"], parameter["name"])] = parameter
            responses = operation.get("responses") or {}
            success_statuses = sorted(
                (status for status in responses if str(status).startswith("2")),
                key=lambda status: (str(status) not in {"200", "201", "202", "204"}, str(status)),
            )
            response_schema = None
            for status in success_statuses:
                response = responses.get(status) or {}
                json_content = _json_media_content(response.get("content"))
                if isinstance(json_content.get("schema"), dict):
                    response_schema = json_content["schema"]
                    break
            success_status = next((str(status) for status in success_statuses if str(status).isdigit()), "200")
            request_content = (operation.get("requestBody") or {}).get("content") or {}
            json_request = _json_media_content(request_content)
            operations.append({
                "operationId": operation_id,
                "method": method.upper(),
                "path": route,
                "successStatus": success_status,
                "parameters": [
                    {
                        "name": parameter.get("name"),
                        "in": parameter.get("in"),
                        "required": bool(parameter.get("required")),
                        "schema": parameter.get("schema") or {},
                    }
                    for parameter in parameters_by_key.values()
                ],
                "requestSchema": json_request.get("schema") if isinstance(json_request, dict) else None,
                "responseSchema": response_schema,
            })
    return operations


def _save_db_scenario_yaml(path: str, scenarios: list[dict]) -> str:
    """Validate and save UI-authored scenarios in the runner's standard YAML format."""
    if not isinstance(scenarios, list) or not scenarios or not all(isinstance(item, dict) for item in scenarios):
        raise ValueError("保存するシナリオがありません")
    document = {"scenarios": {"defaults": {"engine": "postgres"}, "list": scenarios}}
    text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, default_flow_style=False)
    parsed = parse_scenarios(text)
    if len(parsed) != len(scenarios):
        raise ValueError("シナリオをすべて検証できませんでした")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return str(target)


def _dispatch(command: str, args: dict) -> object:
    if command == "parse_ddl_catalog":
        from src.ddl_catalog import parse_ddl
        return parse_ddl(args.get("text", ""))
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
    if command == "list_db_scenario_operations":
        return _list_db_scenario_operations(args["path"])
    if command == "load_db_scenario_templates":
        text = Path(args["path"]).read_text(encoding="utf-8")
        parse_scenarios(text)
        data = yaml.safe_load(text)["scenarios"]
        items = data if isinstance(data, list) else data["list"]
        defaults = {} if isinstance(data, list) else data.get("defaults", {})
        for item in items:
            if item.get("db_check") and not item["db_check"].get("engine"):
                item["db_check"]["engine"] = defaults.get("engine", "postgres")
        return items
    if command == "save_db_scenario_yaml":
        return _save_db_scenario_yaml(args["path"], args.get("scenarios"))
    if command == "create_operation_document":
        return create_operation_document(args.get("source_path", ""), args["route"], args["method"],
                                         args["operation_id"], args["statuses"], args.get("request_body", True))
    if command == "load_operation_body_contract":
        return load_operation_body_contract(args["path"], args["operation_id"])
    if command == "save_operation_body_contract":
        return save_operation_body_contract(
            args["source_path"],
            args["destination_path"],
            args["operation_id"],
            args["request_body_required"],
            args.get("request_body_schema"),
            args["response_status"],
            args.get("response_body_schema"),
            args.get("error_db_unchanged"),
            args.get("response_body_empty", False),
        )
    if command == "login_operation_hints":
        return validators.login_operation_hints(args["path"], args["operation_id"])
    if command == "validate_login_request_contract":
        return validators.validate_login_request_contract(args["path"], args["operation_id"], args.get("body"))
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
