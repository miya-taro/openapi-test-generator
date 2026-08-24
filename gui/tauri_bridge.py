#!/usr/bin/env python3
"""Tauri(Rust)側から呼び出す、既存validators.pyの薄いCLIブリッジ。

標準入力からJSON({"command": ..., "args": {...}})を1回だけ受け取り、
結果をJSONで標準出力に1行だけ返す。パス系の引数はWindowsで空白・日本語を含みうるため、
コマンドライン引数ではなく標準入力（UTF-8）でやり取りする。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validators  # noqa: E402


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


def _dispatch(command: str, args: dict) -> object:
    if command == "servers_url":
        return _servers_url(args["path"])
    if command == "list_operations":
        return validators.list_operations(args["path"])
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
