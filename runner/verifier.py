from __future__ import annotations
from models import RunResult, ResponseSchema
from response_validator import validate_body

# Verdict constants
PASS = "OK"
FAIL = "NG"
WARN = "WARNING"
SKIP = "SKIP"


def _find_header(actual_headers: dict[str, str], name: str) -> str | None:
    """HTTPヘッダ名は大文字小文字を区別しないため、大小無視で探す。"""
    target = name.lower()
    for k, v in actual_headers.items():
        if k.lower() == target:
            return v
    return None


def verify(result: RunResult, schema: ResponseSchema) -> tuple[str, str]:
    """Return (verdict, detail). verdict is one of OK/NG/WARNING/SKIP."""
    if result.error and result.curl_exit_code != 0:
        if result.curl_exit_code == 28:
            return FAIL, f"タイムアウト (curl exit 28)"
        return FAIL, f"curl エラー: {result.error}"

    # Level 1: status code
    if result.actual_status != schema.expected_status:
        return FAIL, (
            f"ステータス不一致: 期待={schema.expected_status}, "
            f"実測={result.actual_status}"
        )

    fail_details: list[str] = []
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
        if not actual_ct.startswith(schema.expected_content_type):
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
            fail_details.append(
                f"{header_name}不一致: 期待={expected_value}, 実測={actual_value!r}"
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
