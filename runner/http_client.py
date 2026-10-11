from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import DEFAULT_REQUEST_TIMEOUT, EXIT_ERROR, EXIT_OK, EXIT_TIMEOUT, RunCase, RunResult
from request_builder import (
    EMPTY_VALUE_MARKER,
    OMIT_MARKERS,
    PreparedBody,
    build_operation_header_and_cookie_values,
    build_request_body,
    build_url,
)
from src.security_payload import AUTH_NONE_MARKER, OPENAPI_SECURITY_PARAM, parse_security_payload
from src.cmd_escape import quote_cmd_arg

REQUEST_TIMEOUT = DEFAULT_REQUEST_TIMEOUT


def _resolve_auth_header() -> str | None:
    """全リクエストに付与する認証ヘッダ文字列（"Name: Value"）を解決する。

    優先順位:
    1. TEST_AUTH_HEADER_NAME / TEST_AUTH_HEADER_VALUE
       （--auth-config でログインして取得したトークンを runner.py が設定する）
    2. TEST_AUTH_TOKEN（従来の固定Bearerトークン方式。後方互換のため維持）
    """
    header_name = os.environ.get("TEST_AUTH_HEADER_NAME")
    header_value = os.environ.get("TEST_AUTH_HEADER_VALUE")
    if header_name and header_value:
        return f"{header_name}: {header_value}"

    token = os.environ.get("TEST_AUTH_TOKEN")
    if token:
        return f"Authorization: Bearer {token}"

    return None


def _mask_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        text = text.replace(secret, "***MASKED***")
    return text


def execute(case: RunCase, base_url: str, session: requests.Session | None = None) -> RunResult:
    return execute_with_openapi(case, base_url, None, session)


def execute_with_openapi(
    case: RunCase,
    base_url: str,
    openapi: dict | None,
    session: requests.Session | None = None,
    persist_cookies: bool = False,
) -> RunResult:
    url = build_url(base_url, case, openapi)
    prepared_body = build_request_body(case, openapi)
    return _send_request(case, url, prepared_body, session, persist_cookies, openapi)


def _send_request(
    case: RunCase,
    url: str,
    prepared_body: PreparedBody | None,
    session: requests.Session | None = None,
    persist_cookies: bool = False,
    openapi: dict | None = None,
) -> RunResult:
    headers: dict[str, str] = {}
    cookies: dict[str, str] = {}
    security_payload = None
    is_auth_probe = case.param_name == OPENAPI_SECURITY_PARAM or case.input_value == AUTH_NONE_MARKER
    if case.param_name == OPENAPI_SECURITY_PARAM and case.input_value != AUTH_NONE_MARKER:
        try:
            security_payload = parse_security_payload(case.input_value)
        except ValueError as e:
            return RunResult(
                case=case, actual_status=0, actual_body="", actual_headers={}, elapsed_ms=0.0,
                exit_code=EXIT_ERROR, curl_command="", error=str(e),
            )

    # 記録用コマンド文字列（結果 Excel に保存される）からは機密値をマスクする
    secrets: list[str] = []

    baseline_headers, baseline_cookies = build_operation_header_and_cookie_values(case, openapi)
    headers.update(baseline_headers)
    cookies.update(baseline_cookies)

    # OpenAPI認証プローブは明示した値だけを使い、ログイン認証や環境変数を加えない。
    # 通常のheaderケースも入力値を優先し、それ以外には設定済み認証を追加する。
    if security_payload is not None:
        headers.update(security_payload["headers"])
        cookies.update(security_payload["cookies"])
    else:
        if case.param_in == "header":
            if case.input_value not in OMIT_MARKERS and case.input_value != AUTH_NONE_MARKER:
                headers[case.param_name] = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value
            # （省略）の場合は対象ヘッダだけを送らず、他の必須ヘッダ/cookieは維持する。
        elif case.param_in == "cookie":
            if case.input_value not in OMIT_MARKERS and case.input_value != AUTH_NONE_MARKER:
                cookies[case.param_name] = "" if case.input_value == EMPTY_VALUE_MARKER else case.input_value

        if case.param_in != "header":
            auth_header = _resolve_auth_header()
            if auth_header:
                header_name, _, header_value = auth_header.partition(": ")
                headers[header_name] = header_value
                if header_value:
                    secrets.append(header_value)

    kwargs: dict = {}
    if prepared_body is not None:
        if prepared_body.is_multipart:
            kwargs["files"] = prepared_body.multipart_fields
        else:
            headers.setdefault("Content-Type", "application/json; charset=utf-8")
            if prepared_body.json_body is None:
                kwargs["data"] = "null"
            else:
                kwargs["json"] = prepared_body.json_body

    request = requests.Request(
        method=case.method.upper(),
        url=url,
        headers=headers,
        params=security_payload["query"] if security_payload else None,
        cookies=cookies,
        **kwargs,
    )

    try:
        # 認証プローブは、ログインで得た認証や保持Cookieを意図せず再利用しない。
        # Request.prepare() により、明示した無効値だけでPreparedRequestを作る。
        prepared = (
            request.prepare()
            if session is None or is_auth_probe
            else session.prepare_request(request)
        )
    except Exception as e:  # 例: multipartのエンコードに失敗した場合等
        return RunResult(
            case=case, actual_status=0, actual_body="", actual_headers={}, elapsed_ms=0.0,
            exit_code=EXIT_ERROR, curl_command="", error=f"リクエストの組み立てに失敗しました: {e}",
        )

    cmd_str = _mask_secrets(_curl_command_from_prepared(prepared), secrets)

    # session を共有している場合は接続プーリングのため常に同一 Session.send() を使う。
    # cookie の永続化（--cookie-jar）はオプトインのため、非対象時はレスポンス受信後に
    # 都度クリアすることで、コネクション再利用の性能効果とケース間の独立性を両立する。
    # 認証プローブの応答が Set-Cookie を返しても、通常ケース用の共有Cookie jarに
    # 保存しないよう、プローブには独立したSessionを割り当てる。
    isolated_session = session is None or is_auth_probe
    sender = requests.Session() if isolated_session else session
    try:
        try:
            # response.elapsed はヘッダ受信までの時間しか計測しない（ボディ転送時間を含まない）ため、
            # curl の %{time_total}（応答完了までの総時間）と揃えるために自前で計測する。
            start = time.perf_counter()
            response = sender.send(prepared, timeout=REQUEST_TIMEOUT, allow_redirects=False)
            elapsed_ms = (time.perf_counter() - start) * 1000
        except requests.exceptions.Timeout:
            return RunResult(
                case=case, actual_status=0, actual_body="", actual_headers={}, elapsed_ms=0.0,
                exit_code=EXIT_TIMEOUT, curl_command=cmd_str, error="タイムアウトしました",
            )
        except requests.exceptions.RequestException as e:
            return RunResult(
                case=case, actual_status=0, actual_body="", actual_headers={}, elapsed_ms=0.0,
                exit_code=EXIT_ERROR, curl_command=cmd_str, error=str(e),
            )
    finally:
        if not isolated_session and not persist_cookies:
            session.cookies.clear()
        if isolated_session:
            sender.close()

    return RunResult(
        case=case,
        actual_status=response.status_code,
        actual_body=response.text,
        actual_headers=dict(response.headers),
        elapsed_ms=elapsed_ms,
        exit_code=EXIT_OK,
        curl_command=cmd_str,
        error=None,
    )


def _curl_command_from_prepared(prepared: requests.PreparedRequest) -> str:
    """実際に送信される requests.PreparedRequest から、結果Excel表示用の curl 相当の
    コマンド文字列を組み立てる。

    実行に使う値（メソッド・URL・ヘッダ・ボディ）を独立に再構築するのではなく、
    実際に送信されるオブジェクトそのものから逆算することで、「送信内容」と
    「Excelに記録される内容」が食い違うリスクを構造的に排除している。
    """
    # 固定トークン（curl.exe自身・フラグ）はクォート無し、値（ヘッダ・ボディ・URL）のみ
    # クォート＋エスケープする。src/renderer/excel_output.py の生成時プレビューと
    # 見た目の書式を揃えている。
    parts = ["curl.exe", "-s", "-v", "-X", prepared.method]
    for name, value in prepared.headers.items():
        parts += ["-H", quote_cmd_arg(f"{name}: {value}")]

    body = prepared.body
    if body is not None:
        if isinstance(body, bytes):
            try:
                body = body.decode("utf-8")
            except UnicodeDecodeError:
                body = "<binary body>"
        parts += ["-d", quote_cmd_arg(body)]

    parts += ["--", quote_cmd_arg(prepared.url)]
    return " ".join(parts)


def health_check(base_url: str, health_path: str = "/health") -> bool:
    url = base_url.rstrip("/") + health_path
    try:
        response = requests.get(url, timeout=5)
        return 200 <= response.status_code < 300
    except requests.exceptions.RequestException:
        return False
