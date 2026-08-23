#!/usr/bin/env python3
"""DBシナリオランナー: APIを呼び出し、その結果DBが期待通り変化したかを検証する。

Layer 1（openapi-test-gen/runner.py によるフィールド単位の検証）とは別レイヤの、
業務シナリオ観点のテスト。試験データの初期化・後始末は本ツールの範囲外とし、
既存の runner.py の --setup/--teardown（TRUNCATE 等）で行う想定。
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows のコンソール既定コードページ(cp932等)では日本語出力が文字化け・デコードエラーの
# 原因になるため、標準出力/標準エラーを UTF-8 に固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from auth_login import load_auth_config, perform_login, build_auth_header, AuthLoginError
from config_loader import load_config, get_postgres_config, get_influxdb_config
from db_scenario import load_scenarios, resolve_db_check, resolve_placeholders, ScenarioError, DBScenario
from db_backends import postgres_backend, influx_backend
from http_client import check_curl_available, health_check, _resolve_auth_header
from src.parser import parse_openapi, OpenAPIParseError

CURL_TIMEOUT = 10


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DBシナリオ（API呼び出し→DB検証）を実行する"
    )
    parser.add_argument("scenario_path", help="シナリオ定義 YAML のパス")
    parser.add_argument("openapi_path", help="openapi.json のパス")
    parser.add_argument("--base-url", required=True, help="API サーバーのベース URL")
    parser.add_argument("--config", required=True, metavar="JSON", help="DB 接続情報の設定ファイル")
    parser.add_argument("--health-path", default="/health", help="ヘルスチェック用パス（省略時: /health）")
    parser.add_argument(
        "--auth-config", metavar="JSON",
        help="ログインして認証トークンを取得するための設定ファイル（固定トークンの TEST_AUTH_TOKEN の代わり）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実際の HTTP リクエスト送信・DB接続を行わない（シナリオ/openapi/config の読み込みのみ確認）",
    )
    args = parser.parse_args()

    scenario_path = Path(args.scenario_path)
    if not scenario_path.exists():
        print(f"[ERROR] シナリオファイルが見つかりません: {scenario_path}", file=sys.stderr)
        return 3

    openapi_path = Path(args.openapi_path)
    if not openapi_path.exists():
        print(f"[ERROR] openapi.json が見つかりません: {openapi_path}", file=sys.stderr)
        return 3

    try:
        scenarios = load_scenarios(scenario_path)
    except ScenarioError as e:
        print(f"[ERROR] シナリオファイルの読み込みに失敗しました: {e}", file=sys.stderr)
        return 3

    try:
        openapi = parse_openapi(str(openapi_path))
    except OpenAPIParseError as e:
        print(f"[ERROR] openapi.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 3

    try:
        db_config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] config.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 3

    print(f"[INFO] シナリオ数: {len(scenarios)} 件")

    if args.dry_run:
        print("[DRY-RUN] HTTP リクエスト送信・DB接続を行わずに終了します")
        return 0

    try:
        check_curl_available()
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3

    if not health_check(args.base_url, args.health_path):
        print(f"[ERROR] ヘルスチェック失敗: {args.base_url}{args.health_path}", file=sys.stderr)
        return 3

    # ログインしてトークンを取得（--auth-config 指定時のみ）
    # http_client.py の _resolve_auth_header() が読む環境変数に設定することで、
    # 以降の _call_api() の全リクエストに自動で付与される。
    if args.auth_config:
        try:
            auth_cfg = load_auth_config(args.auth_config)
            token = perform_login(args.base_url, auth_cfg)
            header_name, header_value = build_auth_header(token, auth_cfg)
            os.environ["TEST_AUTH_HEADER_NAME"] = header_name
            os.environ["TEST_AUTH_HEADER_VALUE"] = header_value
            print(f"[INFO] ログインに成功しました（ヘッダ: {header_name}）")
        except AuthLoginError as e:
            print(f"[ERROR] ログインに失敗しました: {e}", file=sys.stderr)
            return 3

    has_fail = False
    # 直前のシナリオのAPIレスポンス。次のシナリオの path_params/body 内の
    # {{response.xxx}} を解決するのに使う（例: create シナリオで作ったIDを
    # 次の update/delete シナリオの path_params に引き継ぐ）。
    previous_response: dict = {}
    for scenario in scenarios:
        ok, detail, api_status, previous_response = _run_scenario(
            scenario, openapi, args.base_url, db_config, previous_response
        )
        verdict = "OK" if ok else "NG"
        print(f"  [{verdict}] {scenario.name} (API: {api_status})")
        if not ok:
            print(f"         {detail}")
            has_fail = True

    return 1 if has_fail else 0


def _run_scenario(
    scenario: DBScenario, openapi: dict, base_url: str, db_config: dict, previous_response: dict
) -> tuple[bool, str, str, dict]:
    """1シナリオを実行する。

    戻り値: (適合したか, 詳細メッセージ, APIステータス表示用文字列, このシナリオのレスポンス)
    最後の要素は次のシナリオへ引き継ぐ previous_response になる。解決に失敗した場合や
    API呼び出しに失敗した場合は、引き継ぎ用のレスポンスは変化させず previous_response をそのまま返す。
    """
    try:
        path, method = _resolve_operation(openapi, scenario.request.operation_id)
    except ScenarioError as e:
        return False, str(e), "ERR", previous_response

    try:
        resolved_path_params = resolve_placeholders(scenario.request.path_params, previous_response)
        resolved_body = resolve_placeholders(scenario.request.body, previous_response)
    except ScenarioError as e:
        return False, f"path_params/bodyの値解決に失敗しました: {e}", "ERR", previous_response

    status, response_json, error = _call_api(base_url, path, method, resolved_path_params, resolved_body)
    if error:
        return False, f"API呼び出しに失敗しました: {error}", "ERR", previous_response

    try:
        resolved_check = resolve_db_check(scenario.db_check, response_json)
    except ScenarioError as e:
        return False, f"APIレスポンスからの値解決に失敗しました: {e}", str(status), response_json

    try:
        if resolved_check.engine == "postgres":
            pg_config = get_postgres_config(db_config)
            ok, detail = postgres_backend.check(resolved_check, pg_config)
        else:
            influx_config = get_influxdb_config(db_config)
            ok, detail = influx_backend.check(resolved_check, influx_config)
    except (ValueError, KeyError) as e:
        return False, f"DB検証でエラーが発生しました: {e}", str(status), response_json

    return ok, detail, str(status), response_json


def _resolve_operation(openapi: dict, operation_id: str) -> tuple[str, str]:
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return path, method.upper()
    raise ScenarioError(f"operationId '{operation_id}' が openapi.json に見つかりません")


def _call_api(
    base_url: str, path: str, method: str, path_params: dict, body: dict
) -> tuple[int, dict, str | None]:
    """curl.exe でAPIを呼び出す。戻り値: (status, response_json, error)"""
    url_path = path
    for name, value in path_params.items():
        url_path = url_path.replace("{" + name + "}", str(value))
    url = base_url.rstrip("/") + url_path

    cmd = [
        "curl.exe", "-s", "-X", method,
        "-w", "\n%{http_code}",
        "--max-time", str(CURL_TIMEOUT),
        url,
    ]

    auth_header = _resolve_auth_header()
    if auth_header:
        cmd += ["-H", auth_header]

    if body:
        cmd += ["-H", "Content-Type: application/json; charset=utf-8", "-d", json.dumps(body, ensure_ascii=False)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return 0, {}, "curl.exe が見つかりません"

    if result.returncode != 0:
        return 0, {}, result.stderr or f"curl exited with code {result.returncode}"

    body_text, _, status_text = result.stdout.rpartition("\n")
    try:
        status = int(status_text.strip())
    except ValueError:
        return 0, {}, f"curl の出力を解析できませんでした: {result.stdout!r}"

    response_json: dict = {}
    if body_text.strip():
        try:
            response_json = json.loads(body_text)
        except json.JSONDecodeError:
            response_json = {}

    return status, response_json, None


if __name__ == "__main__":
    sys.exit(main())
