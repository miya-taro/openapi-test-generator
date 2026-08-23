from __future__ import annotations
import re
from models import RunCase, ResponseSchema
from response_validator import resolve_response_schema

_TIME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*秒")
_EXISTENCE_ONLY_MARKER = "（存在確認のみ）"


def from_run_case(case: RunCase, openapi: dict | None = None) -> ResponseSchema:
    status = _parse_status(case.expected_status)
    content_type = _parse_content_type(case.expected_response_header)
    expected_headers = _parse_expected_headers(case.expected_response_header)
    response_time_ms = _parse_time_ms(case.expected_response_time)
    body_schema = (
        resolve_response_schema(case.operation_id, case.path, case.method, case.expected_status, openapi)
        if openapi is not None
        else None
    )
    return ResponseSchema(
        expected_status=status,
        expected_content_type=content_type,
        expected_response_time_ms=response_time_ms,
        expected_body_schema=body_schema,
        expected_headers=expected_headers,
    )


def _parse_status(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        return 0


def _parse_content_type(raw: str) -> str | None:
    for line in raw.splitlines():
        if line.lower().startswith("content-type:"):
            value = line.split(":", 1)[1].strip()
            # exclude placeholder values
            if "複数" in value or "要確認" in value:
                return None
            return value
    return None


def _parse_expected_headers(raw: str) -> dict:
    """expectedResponseHeader列からContent-Type以外のヘッダ期待値を取り出す。

    値が「（存在確認のみ）」（generatorがOpenAPI定義のheadersセクションから機械的に
    出力するマーカー。具体的な値まではOpenAPI定義から確実には分からないため）の場合は
    ヘッダの存在確認のみを行う（値は None として保持する）。
    """
    headers: dict[str, str | None] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, _, value = line.partition(":")
        name = name.strip()
        value = value.strip()
        if not name or name.lower() == "content-type":
            continue
        if value == _EXISTENCE_ONLY_MARKER or "複数" in value or "要確認" in value:
            headers[name] = None
        else:
            headers[name] = value
    return headers


def _parse_time_ms(raw: str) -> float:
    m = _TIME_PATTERN.search(raw)
    if m:
        return float(m.group(1)) * 1000
    return 3000.0  # default 3 seconds
