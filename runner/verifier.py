from __future__ import annotations
import re

from models import EXIT_TIMEOUT, RunResult, ResponseSchema
from response_validator import validate_body
from sensitive_data import (
    contains_private_key_header,
    credential_findings,
    redact_header_value,
    redact_sensitive_response,
)

# Verdict constants
PASS = "OK"
FAIL = "NG"
WARN = "WARNING"
SKIP = "SKIP"

_PHP_RUNTIME_ERROR = re.compile(
    r"\b(?:Fatal error|Parse error|Uncaught\s+[\w\\]*(?:Error|Exception))\b",
    re.IGNORECASE,
)
_PHP_DIAGNOSTIC = re.compile(
    r"\b(?:Warning|Notice|Deprecated):[^\r\n]*\bin\s+\S+\s+on line\s+\d+",
    re.IGNORECASE,
)
_PYTHON_TRACEBACK = re.compile(r"Traceback \(most recent call last\):")
_STACK_TRACE = re.compile(r"Stack trace:\s*(?:\r?\n)?\s*(?:#\d+|at\s+)", re.IGNORECASE)
_DATABASE_ERROR = re.compile(
    r"\b(?:SQLSTATE\s*\[[0-9A-Z]{5}\](?![0-9A-Z])|ORA-\d{5}\b|PDOException\b|"
    r"mysqli_sql_exception\b|SQLITE_ERROR\b|You have an error in your SQL syntax\b|"
    r"SQL syntax error\b|syntax error at or near\b|unterminated quoted string\b|"
    r"no such table\b|unknown column\b)",
    re.IGNORECASE,
)
def _response_error_leaks(body: str) -> list[str]:
    """レスポンスへ漏れた明確な実行時エラーの種別だけを返す。

    レスポンス本文やファイルパス自体は詳細へ含めず、報告書への二次漏えいを防ぐ。
    """
    findings: list[str] = []
    if _PHP_RUNTIME_ERROR.search(body) or _PHP_DIAGNOSTIC.search(body):
        findings.append("PHPエラー情報の露出")
    if _PYTHON_TRACEBACK.search(body) or _STACK_TRACE.search(body):
        findings.append("スタックトレースの露出")
    if _DATABASE_ERROR.search(body):
        findings.append("データベースエラー情報の露出")
    if contains_private_key_header(body):
        findings.append("秘密鍵ブロックの露出")
    return findings


def _response_credential_leaks(body: str) -> list[str]:
    """既知プロバイダー形式の資格情報を検出し、値を含めず種別だけ返す。

    一般的なJWTや任意の長い文字列は、通常のAPI応答にも現れるため対象外にする。
    """
    return credential_findings(body)


def _content_type_matches(actual_ct: str, expected_ct: str) -> bool:
    """メディアタイプ部分（`;`より前、charset等のパラメータを除いた部分）を
    大小無視で完全一致比較する。

    以前は単純な前方一致（str.startswith）だったため、"application/json" を期待している
    ところに全く別のメディアタイプ "application/json-patch+json" が返ってきても、
    文字列としては前方一致してしまい誤ってOK判定していた（RFC 7231上メディアタイプは
    トークン単位で区別すべきで、部分文字列一致は不正確）。
    """
    actual_media_type = actual_ct.split(";", 1)[0].strip().lower()
    expected_media_type = expected_ct.split(";", 1)[0].strip().lower()
    return actual_media_type == expected_media_type


def _find_header(actual_headers: dict[str, str], name: str) -> str | None:
    """HTTPヘッダ名は大文字小文字を区別しないため、大小無視で探す。"""
    target = name.lower()
    for k, v in actual_headers.items():
        if k.lower() == target:
            return v
    return None


def verify(result: RunResult, schema: ResponseSchema) -> tuple[str, str]:
    """Return (verdict, detail). verdict is one of OK/NG/WARNING/SKIP."""
    result.report_body = redact_sensitive_response(
        result.actual_body, schema.expected_body_schema
    )
    if result.error:
        if result.exit_code == EXIT_TIMEOUT:
            return FAIL, "タイムアウト"
        return FAIL, f"リクエストエラー: {result.error}"

    leak_details = [
        *_response_error_leaks(result.actual_body),
        *_response_credential_leaks(result.actual_body),
    ]

    # Level 1: status code
    if result.actual_status != schema.expected_status:
        status_detail = (
            f"ステータス不一致: 期待={schema.expected_status}, "
            f"実測={result.actual_status}"
        )
        return FAIL, "; ".join([status_detail, *leak_details])

    fail_details: list[str] = list(leak_details)
    warn_details: list[str] = []

    # Level 2: response time
    if result.elapsed_ms > schema.expected_response_time_ms:
        warn_details.append(
            f"応答時間超過: {result.elapsed_ms:.0f}ms > "
            f"{schema.expected_response_time_ms:.0f}ms"
        )

    # Level 3: Content-Type
    if schema.expected_content_type:
        actual_ct = result.actual_headers.get("Content-Type", "")
        if not _content_type_matches(actual_ct, schema.expected_content_type):
            fail_details.append(
                f"Content-Type不一致: 期待={schema.expected_content_type}, "
                f"実測={actual_ct!r}"
            )

    # Level 3: Content-Type以外の期待ヘッダ（存在確認のみ、または具体的な値の一致）
    for header_name, expected_value in schema.expected_headers.items():
        actual_value = _find_header(result.actual_headers, header_name)
        if actual_value is None:
            fail_details.append(f"ヘッダ不足: {header_name} が存在しません")
        elif expected_value is not None and actual_value != expected_value:
            safe_expected = redact_header_value(header_name, expected_value)
            safe_actual = redact_header_value(header_name, actual_value)
            fail_details.append(
                f"{header_name}不一致: 期待={safe_expected}, 実測={safe_actual!r}"
            )

    # Level 4: レスポンスボディの JSON Schema 適合
    if schema.expected_body_schema:
        body_errors = validate_body(result.actual_body, schema.expected_body_schema)
        if body_errors:
            fail_details.append("ボディ不適合: " + " / ".join(body_errors))

    if fail_details:
        return FAIL, "; ".join(fail_details)
    if warn_details:
        return WARN, "; ".join(warn_details)
    return PASS, ""
