#!/usr/bin/env python3
"""DBシナリオランナー: APIを呼び出し、その結果DBが期待通り変化したかを検証する。

Layer 1（openapi-test-gen/runner.py によるフィールド単位の検証）とは別レイヤの、
業務シナリオ観点のテスト。テーブル全体のTRUNCATE等、試験実行全体を通した初期化・後始末は
本ツールの範囲外とし、既存の runner.py の --setup/--teardown で行う想定。
一方、個々のシナリオが必要とする前提データ（factory. シナリオYAMLの given）は
本ツール自身がAPI呼び出しの前にDBへ直接INSERTし、シナリオ終了時に削除まで面倒を見る。
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from pathlib import Path

import requests

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

from auth_login import (
    auth_config_for_profile, load_auth_config, perform_login, build_auth_header, AuthLoginError,
)
from config_loader import load_config, get_postgres_config, get_influxdb_config
import db_factory
from db_scenario import load_scenarios, resolve_db_check, resolve_placeholders, ScenarioError, DBScenario
from db_backends import postgres_backend, influx_backend
import response_check as response_check_module
import db_scenario_report
from http_client import health_check, _resolve_auth_header
from junit_writer import write_junit_xml_scenarios
from models import DEFAULT_REQUEST_TIMEOUT
from src.parser import parse_openapi, OpenAPIParseError

REQUEST_TIMEOUT = DEFAULT_REQUEST_TIMEOUT
_RESPONSE_PLACEHOLDER = re.compile(r"\{\{\s*response\.")


class _ScenarioSessions:
    """Run-local sessions, isolated by named auth profile and closed on every exit path."""

    def __init__(self):
        self.default = requests.Session()
        self.named: dict[str, requests.Session] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.default.close()
        for session in self.named.values():
            session.close()

    def for_profile(self, name: str) -> requests.Session:
        if name not in self.named:
            self.named[name] = requests.Session()
        return self.named[name]


def _contains_response_placeholder(value) -> bool:
    if isinstance(value, str):
        return _RESPONSE_PLACEHOLDER.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_response_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_response_placeholder(item) for item in value)
    return False


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
        "--skip-health-check", action="store_true",
        help="実行前の疎通確認（ヘルスチェック）を行わない",
    )
    parser.add_argument(
        "--auth-config", metavar="JSON",
        help="ログインして認証トークンを取得するための設定ファイル（固定トークンの TEST_AUTH_TOKEN の代わり）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="実際の HTTP リクエスト送信・DB接続を行わない（シナリオ/openapi/config の読み込みのみ確認）",
    )
    parser.add_argument(
        "--report-output", metavar="XLSX",
        help="シナリオ名・判定・APIステータス・詳細を一覧できるExcelレポートの出力先（任意）",
    )
    parser.add_argument(
        "--junit-xml", metavar="XML",
        help="実行結果を JUnit XML 形式でも出力する（CIダッシュボード連携用。任意）",
    )
    parser.add_argument(
        "--case-ids", metavar="IDS",
        help="指定した試験IDだけを実行する（カンマ区切り。依存するresponse参照ケースは対象外）",
    )
    parser.add_argument(
        "--cookie-jar", action="store_true",
        help="セッションCookieをシナリオ実行全体で自動的に維持する。"
        "DBシナリオは元々順次実行のため --parallel のような制約はない",
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

    if args.case_ids:
        requested_ids = {case_id.strip() for case_id in args.case_ids.split(",") if case_id.strip()}
        if not requested_ids:
            print("[ERROR] --case-ids に有効な試験IDがありません", file=sys.stderr)
            return 4
        available_ids = {scenario.case_id for scenario in scenarios}
        missing_ids = requested_ids - available_ids
        if missing_ids:
            print(f"[ERROR] 試験IDが見つかりません: {', '.join(sorted(missing_ids))}", file=sys.stderr)
            return 4
        selected = [scenario for scenario in scenarios if scenario.case_id in requested_ids]
        dependent = [
            scenario.case_id for scenario in selected
            if _contains_response_placeholder({
                "request": {
                    "body": scenario.request.body,
                    "pathParams": scenario.request.path_params,
                },
                "given": [item.fields for item in scenario.given],
                "dbCheck": scenario.db_check.__dict__ if scenario.db_check else None,
            })
        ]
        if dependent:
            print(
                "[ERROR] 直前シナリオのresponseに依存するDBケースは単独再実行できません: "
                + ", ".join(dependent),
                file=sys.stderr,
            )
            return 4
        scenarios = selected

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

    required_profiles = {scenario.auth_profile for scenario in scenarios if scenario.auth_profile}
    auth_cfg = None
    if args.auth_config:
        try:
            auth_cfg = load_auth_config(args.auth_config)
            for profile_name in required_profiles:
                auth_config_for_profile(auth_cfg, profile_name)
        except AuthLoginError as e:
            print(f"[ERROR] 認証設定の読み込みに失敗しました: {e}", file=sys.stderr)
            return 3
    elif required_profiles:
        print(
            "[ERROR] auth_profile を使うシナリオには --auth-config が必要です",
            file=sys.stderr,
        )
        return 3

    print(f"[INFO] シナリオ数: {len(scenarios)} 件")

    if args.dry_run:
        print("[DRY-RUN] HTTP リクエスト送信・DB接続を行わずに終了します")
        return 0

    if not args.skip_health_check and not health_check(args.base_url, args.health_path):
        print(f"[ERROR] ヘルスチェック失敗: {args.base_url}{args.health_path}", file=sys.stderr)
        return 3

    # 全シナリオを通して1つの Session を共有する（コネクションプーリングによる高速化のため）。
    # セッションCookieの永続化（--cookie-jar）はオプトインのため、非指定時は各リクエスト後に
    # Cookie をクリアすることで、コネクション再利用の性能効果とシナリオ間の独立性を両立する。
    sessions = _ScenarioSessions()
    session = sessions.default

    with sessions:
        profile_sessions: dict[str, tuple[requests.Session, tuple[str, str]]] = {}
        # ログインしてトークンを取得（--auth-config 指定時のみ）
        # http_client.py の _resolve_auth_header() が読む環境変数に設定することで、
        # 以降の _call_api() の全リクエストに自動で付与される。
        needs_default_auth = not required_profiles or any(
            scenario.auth_profile is None for scenario in scenarios
        )
        if auth_cfg and needs_default_auth:
            try:
                default_cfg = auth_config_for_profile(auth_cfg, None)
                token = perform_login(args.base_url, default_cfg, session)
                header_name, header_value = build_auth_header(token, default_cfg)
                os.environ["TEST_AUTH_HEADER_NAME"] = header_name
                os.environ["TEST_AUTH_HEADER_VALUE"] = header_value
                print(f"[INFO] ログインに成功しました（ヘッダ: {header_name}）")
            except AuthLoginError as e:
                print(f"[ERROR] ログインに失敗しました: {e}", file=sys.stderr)
                return 3
            if not args.cookie_jar:
                session.cookies.clear()

        for profile_name in sorted(required_profiles):
            try:
                profile_cfg = auth_config_for_profile(auth_cfg, profile_name)
                profile_session = sessions.for_profile(profile_name)
                token = perform_login(args.base_url, profile_cfg, profile_session)
                profile_sessions[profile_name] = (
                    profile_session,
                    build_auth_header(token, profile_cfg),
                )
                print(f"[INFO] ログインに成功しました（認証プロファイル: {profile_name}）")
            except AuthLoginError as e:
                print(f"[ERROR] 認証プロファイル「{profile_name}」のログインに失敗しました: {e}", file=sys.stderr)
                return 3
            if not args.cookie_jar:
                profile_session.cookies.clear()

        has_fail = False
        report_rows: list[tuple[str, str, bool, str, str]] = []
        all_cleanup_errors: list[str] = []
        # 直前のシナリオのAPIレスポンス。次のシナリオの path_params/body 内の
        # {{response.xxx}} を解決するのに使う（例: create シナリオで作ったIDを
        # 次の update/delete シナリオの path_params に引き継ぐ）。
        previous_response: dict = {}
        for scenario in scenarios:
            case_session = session
            case_auth_header = None
            if scenario.auth_profile is not None:
                case_session, case_auth_header = profile_sessions[scenario.auth_profile]
            ok, detail, api_status, previous_response, cleanup_errors = _run_scenario(
                scenario, openapi, args.base_url, db_config, previous_response,
                case_session, args.cookie_jar, case_auth_header,
            )
            verdict = "OK" if ok else "NG"
            role_label = f"（認証: {scenario.auth_profile}）" if scenario.auth_profile else ""
            report_name = f"{scenario.name}{role_label}"
            print(f"  [{verdict}] {scenario.case_id} {report_name} (API: {api_status})")
            if not ok:
                print(f"         {detail}")
                has_fail = True
            report_rows.append((scenario.case_id, report_name, ok, api_status, detail))
            all_cleanup_errors.extend(cleanup_errors)

        if all_cleanup_errors:
            print(
                f"[WARN] 前提データ（given）のクリーンアップに失敗した件数: {len(all_cleanup_errors)} 件"
                "（DBにテストデータが残留している可能性があります。詳細は上記の各[WARN]行を参照）",
                file=sys.stderr,
            )

        if args.report_output:
            db_scenario_report.write_report(report_rows, args.report_output)
            print(f"[INFO] レポートを {args.report_output} に出力しました")

        if args.junit_xml:
            write_junit_xml_scenarios(report_rows, args.junit_xml)
            print(f"[INFO] JUnit XML を出力しました: {args.junit_xml}")

        return 1 if has_fail else 0


def _run_scenario(
    scenario: DBScenario, openapi: dict, base_url: str, db_config: dict, previous_response: dict,
    session: requests.Session, persist_cookies: bool = False,
    auth_header: tuple[str, str] | None = None,
) -> tuple[bool, str, str, dict, list[str]]:
    """1シナリオを実行する。

    戻り値: (適合したか, 詳細メッセージ, APIステータス表示用文字列, このシナリオのレスポンス,
    前提データのクリーンアップ失敗メッセージ一覧)。4番目の要素は次のシナリオへ引き継ぐ
    previous_response になる。解決に失敗した場合やAPI呼び出しに失敗した場合は、引き継ぎ用の
    レスポンスは変化させず previous_response をそのまま返す。

    scenario.given がある場合は、request の前に前提データをDBへ直接INSERTする（factory）。
    投入した行は as名で given_data に控え、path_params/body/db_check から
    `{{given.<as名>.<カラム>}}` で参照できるようにする。投入した行はシナリオ終了時に
    （成否に関わらず）作成順の逆順で必ず削除する。クリーンアップの失敗はシナリオ自体の
    判定は変えないが（既に確定した合否を覆すべきではないため）、握りつぶさず戻り値で
    呼び出し元（main()）まで伝播し、実行全体のサマリで可視化する（DBにテストデータが
    残留し続けていることに誰も気づけない、という事態を避けるため）。
    """
    given_data: dict[str, dict] = {}
    created: list[tuple[str, dict]] = []

    def _execute() -> tuple[bool, str, str, dict]:
        for item in scenario.given:
            try:
                pg_config = get_postgres_config(db_config)
            except (ValueError, KeyError) as e:
                return False, f"前提データ投入用のDB接続設定が不正です: {e}", "ERR", previous_response
            try:
                fields = resolve_placeholders(item.fields, previous_response, given_data)
                row, primary_key = db_factory.create(pg_config, item.table, fields)
            except db_factory.FactoryError as e:
                return False, f"前提データの投入に失敗しました（{item.table}）: {e}", "ERR", previous_response
            given_data[item.as_name] = row
            created.append((item.table, primary_key))

        try:
            path, method = _resolve_operation(openapi, scenario.request.operation_id)
        except ScenarioError as e:
            return False, str(e), "ERR", previous_response

        try:
            resolved_path_params = resolve_placeholders(scenario.request.path_params, previous_response, given_data)
            resolved_body = resolve_placeholders(scenario.request.body, previous_response, given_data)
        except ScenarioError as e:
            return False, f"path_params/bodyの値解決に失敗しました: {e}", "ERR", previous_response

        call_args = (base_url, path, method, resolved_path_params, resolved_body, session, persist_cookies)
        status, response_json, error = (
            _call_api(*call_args, auth_header=auth_header)
            if auth_header is not None
            else _call_api(*call_args)
        )
        if error:
            return False, f"API呼び出しに失敗しました: {error}", "ERR", previous_response

        failures: list[str] = []

        if scenario.response_check is not None:
            ok, detail = response_check_module.check(scenario.response_check, status, response_json)
            if not ok:
                failures.append(detail)

        if scenario.db_check is not None:
            try:
                resolved_check = resolve_db_check(scenario.db_check, response_json, given_data)
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

            if not ok:
                failures.append(detail)

        return not failures, "; ".join(failures), str(status), response_json

    try:
        result = _execute()
    finally:
        cleanup_errors: list[str] = []
        for table, primary_key in reversed(created):
            try:
                pg_config = get_postgres_config(db_config)
                db_factory.delete(pg_config, table, primary_key)
            except Exception as e:
                msg = f"前提データのクリーンアップに失敗しました（{table} {primary_key}）: {e}"
                print(f"[WARN] {msg}", file=sys.stderr)
                cleanup_errors.append(msg)

    return (*result, cleanup_errors)


def _resolve_operation(openapi: dict, operation_id: str) -> tuple[str, str]:
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return path, method.upper()
    raise ScenarioError(f"operationId '{operation_id}' が openapi.json に見つかりません")


def _call_api(
    base_url: str, path: str, method: str, path_params: dict, body: dict,
    session: requests.Session | None = None, persist_cookies: bool = False,
    auth_header: tuple[str, str] | None = None,
) -> tuple[int, dict, str | None]:
    """requests でAPIを呼び出す。戻り値: (status, response_json, error)"""
    url_path = path
    for name, value in path_params.items():
        url_path = url_path.replace("{" + name + "}", str(value))
    url = base_url.rstrip("/") + url_path

    headers: dict[str, str] = {}
    if auth_header is None:
        configured_header = _resolve_auth_header()
        if configured_header:
            header_name, _, header_value = configured_header.partition(": ")
            headers[header_name] = header_value
    else:
        headers[auth_header[0]] = auth_header[1]

    kwargs: dict = {"headers": headers, "timeout": REQUEST_TIMEOUT}
    if body:
        kwargs["json"] = body

    sender = session if session is not None else requests
    try:
        response = sender.request(method, url, **kwargs)
    except requests.exceptions.RequestException as e:
        return 0, {}, str(e)
    finally:
        if session is not None and not persist_cookies:
            session.cookies.clear()

    response_json: dict = {}
    if response.text.strip():
        try:
            response_json = response.json()
        except ValueError:
            response_json = {}

    return response.status_code, response_json, None


if __name__ == "__main__":
    sys.exit(main())
