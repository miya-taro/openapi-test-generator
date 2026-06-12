from __future__ import annotations
from models import RunResult, ResponseSchema

# Verdict constants
PASS = "OK"
FAIL = "NG"
WARN = "WARNING"
SKIP = "SKIP"


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

    if fail_details:
        return FAIL, "; ".join(fail_details)
    if warn_details:
        return WARN, "; ".join(warn_details)
    return PASS, ""
