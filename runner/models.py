from __future__ import annotations
from dataclasses import dataclass, field

# RunResult.exit_code の意味（requests 移行後は curl の終了コードではなく、
# このツール自身が定義する分類コード）。
EXIT_OK = 0
EXIT_TIMEOUT = 1
EXIT_ERROR = 2

# HTTPリクエストのタイムアウト秒数（http_client.py/auth_login.py/db_scenario_runner.py で共有）。
DEFAULT_REQUEST_TIMEOUT = 10


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
    exit_code: int
    curl_command: str = ""
    error: str | None = None
    # Excel証跡用。verify() が OpenAPI writeOnly 定義も含めて伏せた本文を設定する。
    report_body: str | None = None


@dataclass
class ResponseSchema:
    expected_status: int | None
    expected_content_type: str | None
    expected_response_time_ms: float
    expected_body_schema: dict | None = None
    expected_status_class: int | None = None
    expected_statuses: frozenset[int] = frozenset()
    require_documented_status: bool = False
    expected_body_schemas_by_status: dict[int, dict | None] = field(default_factory=dict)
    expected_body_schemas_by_status_and_content_type: dict[int, dict[str, dict]] = field(default_factory=dict)
    expected_content_types_by_status: dict[int, frozenset[str]] = field(default_factory=dict)
    expected_header_schemas_by_status: dict[int, dict[str, dict]] = field(default_factory=dict)
    expected_header_names_by_status: dict[int, frozenset[str]] = field(default_factory=dict)
    # ヘッダ名 -> 期待値（存在確認のみの場合は None）。Content-Type は
    # expected_content_type 側で扱うためここには含めない。
    expected_headers: dict = field(default_factory=dict)
