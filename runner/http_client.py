from __future__ import annotations
import os
import shutil
import subprocess
from models import RunCase, RunResult
from request_builder import build_url, build_body_args

CURL_TIMEOUT = 10


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


def check_curl_available() -> None:
    if shutil.which("curl.exe") is None:
        raise RuntimeError(
            "curl.exe が見つかりません。"
            "Windows の curl.exe が PATH に含まれているか確認してください。"
        )


def execute(case: RunCase, base_url: str) -> RunResult:
    url = build_url(base_url, case)
    openapi = None  # baseline generation handled by runner.py which passes openapi
    body_args = build_body_args(case, openapi)
    return _run_curl(case, url, body_args)


def execute_with_openapi(case: RunCase, base_url: str, openapi: dict | None) -> RunResult:
    from request_builder import build_url, build_body_args
    url = build_url(base_url, case, openapi)
    body_args = build_body_args(case, openapi)
    return _run_curl(case, url, body_args)


def _run_curl(case: RunCase, url: str, body_args: list[str]) -> RunResult:
    cmd = ["curl.exe", "-s", "-v", "-X", case.method.upper(),
           "-D", "-",
           "-w", "\n%{http_code}\n%{time_total}",
           "--max-time", str(CURL_TIMEOUT)]

    # 記録用コマンド文字列（結果 Excel に保存される）からは機密値をマスクする
    secrets: list[str] = []

    # 認証ヘッダの処理
    # param_in == "header" かつ Authorization 系フィールドが対象の場合は env var より優先
    if case.param_in == "header":
        if case.input_value != "（認証ヘッダなし）":
            cmd += ["-H", f"{case.param_name}: {case.input_value}"]
        # （認証ヘッダなし）の場合は何も追加しない（auth なしケース）
    else:
        auth_header = _resolve_auth_header()
        if auth_header:
            cmd += ["-H", auth_header]
            _, _, header_value = auth_header.partition(": ")
            if header_value:
                secrets.append(header_value)

    if case.param_in == "body":
        cmd += ["-H", "Content-Type: application/json; charset=utf-8"]

    cmd += body_args
    cmd += ["--", url]

    cmd_str = _mask_secrets(" ".join(cmd), secrets)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError:
        return RunResult(
            case=case,
            actual_status=0,
            actual_body="",
            actual_headers={},
            elapsed_ms=0.0,
            curl_exit_code=127,
            curl_command=cmd_str,
            error="curl.exe not found",
        )

    if result.returncode != 0:
        return RunResult(
            case=case,
            actual_status=0,
            actual_body=result.stdout,
            actual_headers={},
            elapsed_ms=0.0,
            curl_exit_code=result.returncode,
            curl_command=cmd_str,
            error=result.stderr or f"curl exited with code {result.returncode}",
        )

    raw = result.stdout
    headers, body = _split_headers_body(raw)

    lines = body.rsplit("\n", 2)
    if len(lines) < 3:
        return RunResult(
            case=case,
            actual_status=0,
            actual_body=raw,
            actual_headers=headers,
            elapsed_ms=0.0,
            curl_exit_code=result.returncode,
            curl_command=cmd_str,
            error="Unexpected curl output format",
        )

    body_text = lines[0]
    try:
        http_code = int(lines[1].strip())
        elapsed_ms = float(lines[2].strip()) * 1000
    except ValueError:
        return RunResult(
            case=case,
            actual_status=0,
            actual_body=body_text,
            actual_headers=headers,
            elapsed_ms=0.0,
            curl_exit_code=result.returncode,
            curl_command=cmd_str,
            error=f"Could not parse curl output: {raw!r}",
        )

    return RunResult(
        case=case,
        actual_status=http_code,
        actual_body=body_text,
        actual_headers=headers,
        elapsed_ms=elapsed_ms,
        curl_exit_code=0,
        curl_command=cmd_str,
        error=None,
    )


def _split_headers_body(raw: str) -> tuple[dict[str, str], str]:
    """Split curl -D - output into (headers dict, body+metrics string)."""
    # curl -D - puts headers then blank line then body
    # Headers block ends at first \r\n\r\n or \n\n
    for sep in ("\r\n\r\n", "\n\n"):
        idx = raw.find(sep)
        if idx != -1:
            header_block = raw[:idx]
            body_part = raw[idx + len(sep):]
            return _parse_header_block(header_block), body_part
    return {}, raw


def _parse_header_block(block: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("HTTP/"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            headers[key.strip()] = val.strip()
    return headers


def health_check(base_url: str, health_path: str = "/health") -> bool:
    url = base_url.rstrip("/") + health_path
    try:
        result = subprocess.run(
            # "/dev/null" は Windows のネイティブ curl.exe では有効な出力先として扱われない
            # ことがあるため、os.devnull（Windows では "nul"）を使う。
            ["curl.exe", "-s", "-o", os.devnull, "-w", "%{http_code}",
             "--max-time", "5", "--", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.returncode == 0 and result.stdout.strip().startswith("2")
    except FileNotFoundError:
        return False
