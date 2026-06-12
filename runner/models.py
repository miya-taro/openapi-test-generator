from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class RunCase:
    id: str
    operation_id: str
    path: str
    method: str
    param_in: str
    param_name: str
    input_value: str
    expected_status: str
    expected_response_body: str
    expected_response_header: str
    expected_response_time: str
    expected_result: str


@dataclass
class RunResult:
    case: RunCase
    actual_status: int
    actual_body: str
    actual_headers: dict[str, str]
    elapsed_ms: float
    curl_exit_code: int
    curl_command: str = ""
    error: str | None = None


@dataclass
class ResponseSchema:
    expected_status: int
    expected_content_type: str | None
    expected_response_time_ms: float
