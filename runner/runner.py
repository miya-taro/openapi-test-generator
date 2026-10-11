#!/usr/bin/env python3
"""Automated API test runner."""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# openapi-test-gen 側（src/）の $ref / allOf / oneOf / anyOf 解決済みパーサーを
# 再利用するため、リポジトリルートを sys.path に追加する。
_runner_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_runner_dir))
sys.path.insert(1, str(_runner_dir.parent))

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
from http_client import execute_with_openapi, health_check
from junit_writer import write_junit_xml
from models import RunResult
from response_schema import from_run_case
from verifier import verify, WARN, FAIL
from src.parser import parse_openapi, OpenAPIParseError
from src.db_scope import scopes_for_case
from contract_db_guard import execute_guarded
from sensitive_data import redact_sensitive_text


def _print_case_result(case, result: RunResult, verdict: str, detail: str) -> None:
    status_label = result.actual_status or "ERR"
    print(f"  [{verdict}] {case.id} {case.method} {case.path} → {status_label}")
    if verdict in (FAIL, WARN) and detail:
        print(f"         {detail}")


def _run_all_sequential(
    cases, openapi, args, session: requests.Session
) -> tuple[list[tuple[RunResult, str, str]], bool, bool]:
    results: list[tuple[RunResult, str, str]] = []
    has_fail = False
    has_warn = False

    for case in cases:
        schema = from_run_case(case, openapi)
        result, db_failures = execute_guarded(
            case, openapi, getattr(args, "db_config", None),
            lambda current=case: execute_with_openapi(current, args.base_url, openapi, session, args.cookie_jar),
            getattr(args, "db_evidence", []),
        )
        verdict, detail = verify(result, schema)
        if db_failures:
            verdict, detail = FAIL, "; ".join(filter(None, [detail, *db_failures]))
        _print_case_result(case, result, verdict, detail)

        if verdict == FAIL:
            has_fail = True
            if args.fail_fast:
                results.append((result, verdict, detail))
                break
        elif verdict == WARN:
            has_warn = True

        results.append((result, verdict, detail))

    return results, has_fail, has_warn


def _run_all_parallel(
    cases, openapi, args, session: requests.Session
) -> tuple[list[tuple[RunResult, str, str]], bool, bool]:
    """各ケースは互いに独立している（Layer 2 の DB シナリオと違い、前のケースのレスポンスに
    依存しない）ため、スレッドプールで並列実行できる。Session はコネクションプーリングの
    ために全スレッドで共有する（urllib3 のコネクションプールはスレッドセーフ）。
    --cookie-jar は --parallel と同時指定できないため、この経路では Cookie の永続化は行わない。

    --fail-fast との併用時は、既に走り始めているケースは完了まで実行される（リクエストを
    途中で強制終了することはしない）ため、停止タイミングは「最初のNGを検出した時点」より
    やや後ろにずれる（概算）。
    """
    results: list[tuple[RunResult, str, str]] = []
    has_fail = False
    has_warn = False
    lock = threading.Lock()
    stop_event = threading.Event()

    def _run_one(case):
        if stop_event.is_set():
            return None
        schema = from_run_case(case, openapi)
        result = execute_with_openapi(case, args.base_url, openapi, session)
        verdict, detail = verify(result, schema)
        return case, result, verdict, detail

    with ThreadPoolExecutor(max_workers=args.parallel) as executor:
        futures = [executor.submit(_run_one, case) for case in cases]
        for future in as_completed(futures):
            outcome = future.result()
            if outcome is None:
                continue
            case, result, verdict, detail = outcome
            with lock:
                _print_case_result(case, result, verdict, detail)
                if verdict == FAIL:
                    has_fail = True
                    if args.fail_fast:
                        stop_event.set()
                elif verdict == WARN:
                    has_warn = True
                results.append((result, verdict, detail))

    return results, has_fail, has_warn


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OpenAPIテスト仕様Excelを読み込み、APIに対して試験を実行して結果をExcelに書き出す"
    )
    parser.add_argument("excel_path", help="試験項目 Excel ファイルのパス")
    parser.add_argument("openapi_path", help="openapi.json のパス")
    parser.add_argument("--base-url", required=True, help="API サーバーのベース URL")
    parser.add_argument("--output", help="結果 Excel の出力先（省略時: {元ファイル名}_result.xlsx）")
    parser.add_argument(
        "--junit-xml", metavar="XML",
        help="結果 Excel に加えて、同じ実行結果を JUnit XML 形式でも出力する（CIダッシュボード連携用）",
    )
    parser.add_argument("--health-path", default="/health", help="ヘルスチェック用パス（省略時: /health）")
    parser.add_argument(
        "--skip-health-check", action="store_true",
        help="実行前の疎通確認（ヘルスチェック）を行わない",
    )
    parser.add_argument("--fail-fast", action="store_true", help="Level 1 NG が出た時点で停止")
    parser.add_argument(
        "--case-ids", metavar="IDS",
        help="指定した試験IDだけを実行する（カンマ区切り。失敗ケースの再実行用）",
    )
    parser.add_argument(
        "--parallel", type=int, default=1, metavar="N",
        help="同時実行数（省略時: 1=順次実行）。各ケースは互いに独立しているため並列化可能。"
        "--fail-fast と併用した場合、既に実行中のケースは完了まで走るため停止タイミングは概算になる",
    )
    parser.add_argument("--dry-run", action="store_true", help="実際の HTTP リクエストを送信しない")
    parser.add_argument("--full-body", action="store_true", help="実測ボディを切り捨てずに全文出力する")
    parser.add_argument("--setup", metavar="SQL", help="試験実行前に実行する SQL ファイルのパス")
    parser.add_argument("--teardown", metavar="SQL", help="試験実行後に実行する SQL ファイルのパス（失敗しても続行）")
    parser.add_argument("--config", metavar="JSON", help="DB 接続情報の設定ファイル（--setup / --teardown 指定時は必須）")
    parser.add_argument(
        "--auth-config", metavar="JSON",
        help="ログインして認証トークンを取得するための設定ファイル（固定トークンの TEST_AUTH_TOKEN の代わり）",
    )
    parser.add_argument(
        "--cookie-jar", action="store_true",
        help="セッションCookieを実行全体で自動的に維持する。"
        "ログインでセットされたセッションCookie等が以降の全リクエストに自動で送信される。"
        "--parallel と同時に指定することはできない（並列実行するケース間でCookie状態が"
        "非決定的に混ざり合うため）",
    )
    args = parser.parse_args()

    # --setup / --teardown があるのに --config がない場合
    if (args.setup or args.teardown) and not args.config:
        print(
            "[ERROR] --setup または --teardown を指定する場合は --config が必要です",
            file=sys.stderr,
        )
        return 4

    if args.parallel < 1:
        print("[ERROR] --parallel は 1 以上の整数を指定してください", file=sys.stderr)
        return 4

    if args.cookie_jar and args.parallel > 1:
        print(
            "[ERROR] --cookie-jar と --parallel は同時に指定できません"
            "（並列実行するケース間でCookie状態が非決定的に混ざり合うため）",
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
            print(f"[ERROR] openapi.json の読み込みに失敗しました: {e}", file=sys.stderr)
            return 3
    else:
        print(f"[WARN] openapi.json が見つかりません: {openapi_path}", file=sys.stderr)

    # Load test cases
    try:
        cases = read_excel(excel_path)
    except Exception as e:
        print(f"[ERROR] Excel 読み込みエラー: {e}", file=sys.stderr)
        return 3

    if args.case_ids:
        requested_ids = {case_id.strip() for case_id in args.case_ids.split(",") if case_id.strip()}
        if not requested_ids:
            print("[ERROR] --case-ids に有効な試験IDがありません", file=sys.stderr)
            return 4
        available_ids = {case.id for case in cases}
        missing_ids = requested_ids - available_ids
        if missing_ids:
            print(f"[ERROR] 試験IDが見つかりません: {', '.join(sorted(missing_ids))}", file=sys.stderr)
            return 4
        cases = [case for case in cases if case.id in requested_ids]

    print(f"[INFO] 試験ケース数: {len(cases)} 件")

    guarded = any(scopes_for_case(openapi, case) for case in cases)
    if guarded and (args.parallel > 1 or not args.config):
        print("[ERROR] 異常系のDB変更なし確認にはDB接続設定と逐次実行（parallel=1）が必要です", file=sys.stderr)
        return 4
    args.db_evidence = []

    if args.dry_run:
        print("[DRY-RUN] HTTP リクエストを送信せずに終了します")
        return 0

    # 1. config.json 読み込み（--setup / --teardown 指定時のみ）
    # --setup/--teardown フックは psycopg2 直結（hook_runner.py）のため postgres セクションのみ使う。
    db_config: dict | None = None
    if args.config:
        try:
            db_config = get_postgres_config(load_config(args.config))
        except (FileNotFoundError, ValueError) as e:
            print(f"[ERROR] config.json の読み込みに失敗しました: {e}", file=sys.stderr)
            return 3
    args.db_config = db_config

    # 2. ヘルスチェック（--skip-health-check指定時は行わない）
    if not args.skip_health_check and not health_check(args.base_url, args.health_path):
        print(
            f"[ERROR] ヘルスチェック失敗: {args.base_url}{args.health_path}",
            file=sys.stderr,
        )
        return 3

    # 全ケースを通して1つの Session を共有する（コネクションプーリングによる高速化のため、
    # --parallel 時も含めて常に共有する。urllib3 のコネクションプールはスレッドセーフ）。
    # セッションCookieの永続化（--cookie-jar）はオプトインのため、非指定時は各リクエスト後に
    # Cookie をクリアすることで、コネクション再利用の性能効果とケース間の独立性を両立する。
    #
    # requests/urllib3 の既定プールサイズ（pool_maxsize）は 10 のため、--parallel を
    # それ以上に指定すると、ワーカースレッド数がプールの空き待ちで詰まり並列度が
    # 頭打ちになる（プールが枯渇すると urllib3 が新規接続を都度張っては再利用せず
    # 破棄する動きになり、コネクションプーリングの効果自体が薄れる）。
    # --parallel の値に合わせてプールサイズを引き上げる。
    adapter = requests.adapters.HTTPAdapter(pool_maxsize=max(args.parallel, 10))
    with requests.Session() as session:
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        # 2.5. ログインしてトークンを取得（--auth-config 指定時のみ）
        # http_client.py の _resolve_auth_header() が読む環境変数に設定することで、
        # 以降の全リクエストに自動で付与される。
        if args.auth_config:
            try:
                auth_cfg = load_auth_config(args.auth_config)
                token = perform_login(args.base_url, auth_cfg, session)
                header_name, header_value = build_auth_header(token, auth_cfg)
                os.environ["TEST_AUTH_HEADER_NAME"] = header_name
                os.environ["TEST_AUTH_HEADER_VALUE"] = header_value
                print(f"[INFO] ログインに成功しました（ヘッダ: {header_name}）")
            except AuthLoginError as e:
                print(f"[ERROR] ログインに失敗しました: {e}", file=sys.stderr)
                return 3
            if not args.cookie_jar:
                session.cookies.clear()

        # 3. setup 実行（指定時のみ）
        if args.setup:
            print(f"[INFO] setup 実行: {args.setup}")
            run_hook(args.setup, db_config, is_teardown=False)

        # 4. 全テスト実行
        if args.parallel > 1:
            print(f"[INFO] {args.parallel} 並列で実行します（結果の表示順は完了順になります）")
            results, has_fail, has_warn = _run_all_parallel(cases, openapi, args, session)
        else:
            results, has_fail, has_warn = _run_all_sequential(cases, openapi, args, session)

        # 5. teardown 実行（テスト結果に関わらず常に実行）
        if args.teardown:
            print(f"[INFO] teardown 実行: {args.teardown}")
            run_hook(args.teardown, db_config, is_teardown=True)

    # 6. 結果 Excel 書き出し
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = excel_path.parent / (excel_path.stem + "_result.xlsx")

    try:
        write_results(excel_path, results, output_path, full_body=args.full_body)
        if guarded:
            evidence_path = output_path.with_name(output_path.stem + "-db-evidence.json")
            evidence_path.write_text(redact_sensitive_text(json.dumps(args.db_evidence, ensure_ascii=False, default=str, indent=2)), encoding="utf-8")
        print(f"[INFO] 結果を出力しました: {output_path}")
    except Exception as e:
        print(f"[ERROR] 結果 Excel の書き込みに失敗しました: {e}", file=sys.stderr)
        return 3

    if args.junit_xml:
        try:
            write_junit_xml(results, args.junit_xml)
            print(f"[INFO] JUnit XML を出力しました: {args.junit_xml}")
        except Exception as e:
            print(f"[ERROR] JUnit XML の書き込みに失敗しました: {e}", file=sys.stderr)
            return 3

    if has_fail:
        return 1
    if has_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
