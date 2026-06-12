from __future__ import annotations
import re
from models import RunCase, ResponseSchema

_TIME_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*秒")


def from_run_case(case: RunCase) -> ResponseSchema:
    status = _parse_status(case.expected_status)
    content_type = _parse_content_type(case.expected_response_header)
    response_time_ms = _parse_time_ms(case.expected_response_time)
    return ResponseSchema(
        expected_status=status,
        expected_content_type=content_type,
        expected_response_time_ms=response_time_ms,
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


def _parse_time_ms(raw: str) -> float:
    m = _TIME_PATTERN.search(raw)
    if m:
        return float(m.group(1)) * 1000
    return 3000.0  # default 3 seconds
