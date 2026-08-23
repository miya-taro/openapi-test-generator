#!/usr/bin/env python3
"""Automated API test runner."""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

# openapi-test-gen 側（src/）の $ref / allOf / oneOf / anyOf 解決済みパーサーを
# 再利用するため、リポジトリルートを sys.path に追加する。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows のコンソール既定コードページ(cp932等)では日本語出力が文字化け・デコードエラーの
# 原因になるため、標準出力/標準エラーを UTF-8 に固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from auth_login import load_auth_config, perform_login, build_auth_header, AuthLoginError
from config_loader import load_config, get_postgres_config
from excel_reader import read_excel
from excel_writer import write_results
from hook_runner import run_hook
from http_client import execute_with_openapi, health_check, check_curl_available
from models import RunResult
from response_schema import from_run_case
from verifier import verify, PASS, WARN, FAIL
from src.parser import parse_openapi, OpenAPIParseError


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAPIテスト仕様Excelを読み込み、APIに対して試験を実行して結果をExcelに書き出す"
    )
    parser.add_argument("excel_path", help="試験項目 Excel ファイルのパス")
    parser.add_argument("openapi_path", help="openapi.json のパス")
    parser.add_argument("--base-url", required=True, help="API サーバーのベース URL")
    parser.add_argument("--output", help="結果 Excel の出力先（省略時: {元ファイル名}_result.xlsx）")
    parser.add_argument("--health-path", default="/health", help="ヘルスチェック用パス（省略時: /health）")
    parser.add_argument(
        "--skip-health-check", action="store_true",
        help="実行前の疎通確認（ヘルスチェック）を行わない",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Level 1 NG が出た時点で停止")
    parser.add_argument("--dry-run", action="store_true", help="実際の HTTP リクエストを送信しない")
    parser.add_argument("--full-body", action="store_true", help="実測ボディを切り捨てずに全文出力する")
    parser.add_argument("--setup", metavar="SQL", help="試験実行前に実行する SQL ファイルのパス")
    parser.add_argument("--teardown", metavar="SQL", help="試験実行後に実行する SQL ファイルのパス（失敗しても続行）")
    parser.add_argument("--config", metavar="JSON", help="DB 接続情報の設定ファイル（--setup / --teardown 指定時は必須）")
    parser.add_argument(
        "--auth-config", metavar="JSON",
        help="ログインして認証トークンを取得するための設定ファイル（固定トークンの TEST_AUTH_TOKEN の代わり）",
    )
    args = parser.parse_args()

    # --setup / --teardown があるのに --config がない場合
    if (args.setup or args.teardown) and not args.config:
        print(
            "[ERROR] --setup または --teardown を指定する場合は --config が必要です",
            file=sys.stderr,
        )
        return 4

    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"[ERROR] Excel ファイルが見つかりません: {excel_path}", file=sys.stderr)
        return 3

    openapi_path = Path(args.openapi_path)
    openapi: dict | None = None
    if openapi_path.exists():
        try:
            # $ref / allOf / oneOf / anyOf 解決済み・exclusiveMinimum/Maximum 正規化済みの
            # openapi ドキュメントを取得する（openapi-test-gen と同じパーサーを再利用）。
            openapi = parse_openapi(str(openapi_path))
        except OpenAPIParseError as e:
            print(f"[WARN] openapi.json の読み込みに失敗しました: {e}", file=sys.stderr)
    else:
        print(f"[WARN] openapi.json が見つかりません: {openapi_path}", file=sys.stderr)

    # Load test cases
    try:
        cases = read_excel(excel_path)
    except Exception as e:
        print(f"[ERROR] Excel 読み込みエラー: {e}", file=sys.stderr)
        return 3

    print(f"[INFO] 試験ケース数: {len(cases)} 件")

    if args.dry_run:
        print("[DRY-RUN] HTTP リクエストを送信せずに終了します")
        return 0

    # 1. curl.exe 存在確認
    try:
        check_curl_available()
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3

    # 2. config.json 読み込み（--setup / --teardown 指定時のみ）
    # --setup/--teardown フックは psycopg2 直結（hook_runner.py）のため postgres セクションのみ使う。
    db_config: dict | None = None
    if args.config:
        try:
            db_config = get_postgres_config(load_config(args.config))
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] config.json の読み込みに失敗しました: {e}", file=sys.stderr)
            return 3

    # 3. ヘルスチェック（--skip-health-check指定時は行わない）
    if not args.skip_health_check and not health_check(args.base_url, args.health_path):
        print(
            f"[ERROR] ヘルスチェック失敗: {args.base_url}{args.health_path}",
            file=sys.stderr,
        )
        return 3

    # 3.5. ログインしてトークンを取得（--auth-config 指定時のみ）
    # http_client.py の _resolve_auth_header() が読む環境変数に設定することで、
    # 以降の全リクエストに自動で付与される。
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

    # 4. setup 実行（指定時のみ）
    if args.setup:
        print(f"[INFO] setup 実行: {args.setup}")
        run_hook(args.setup, db_config, is_teardown=False)

    # 5. 全テスト実行
    results: list[tuple[RunResult, str, str]] = []
    has_fail = False
    has_warn = False

    for case in cases:
        schema = from_run_case(case, openapi)
        result = execute_with_openapi(case, args.base_url, openapi)
        verdict, detail = verify(result, schema)

        status_label = result.actual_status or "ERR"
        print(f"  [{verdict}] {case.id} {case.method} {case.path} → {status_label}")

        if verdict == FAIL:
            has_fail = True
            if detail:
                print(f"         {detail}")
            if args.fail_fast:
                results.append((result, verdict, detail))
                break
        elif verdict == WARN:
            has_warn = True
            if detail:
                print(f"         {detail}")

        results.append((result, verdict, detail))

    # 6. teardown 実行（テスト結果に関わらず常に実行）
    if args.teardown:
        print(f"[INFO] teardown 実行: {args.teardown}")
        run_hook(args.teardown, db_config, is_teardown=True)

    # 7. 結果 Excel 書き出し
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = excel_path.parent / (excel_path.stem + "_result.xlsx")

    try:
        write_results(excel_path, results, output_path, full_body=args.full_body)
        print(f"[INFO] 結果を出力しました: {output_path}")
    except Exception as e:
        print(f"[ERROR] 結果 Excel の書き込みに失敗しました: {e}", file=sys.stderr)
        return 3

    if has_fail:
        return 1
    if has_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
