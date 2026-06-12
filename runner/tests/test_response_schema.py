import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from response_schema import from_run_case
from models import RunCase


def make_case(**kwargs) -> RunCase:
    defaults = dict(
        id="TC-001",
        operation_id="op",
        path="/",
        method="GET",
        param_in="query",
        param_name="p",
        input_value="1",
        expected_status="200",
        expected_response_body="",
        expected_response_header="",
        expected_response_time="3秒以内",
        expected_result="",
    )
    defaults.update(kwargs)
    return RunCase(**defaults)


def test_status_parsed():
    schema = from_run_case(make_case(expected_status="201"))
    assert schema.expected_status == 201


def test_content_type_from_header():
    case = make_case(expected_response_header="Content-Type: application/json")
    schema = from_run_case(case)
    assert schema.expected_content_type == "application/json"


def test_no_content_type_when_empty_header():
    schema = from_run_case(make_case(expected_response_header=""))
    assert schema.expected_content_type is None


def test_placeholder_content_type_returns_none():
    case = make_case(expected_response_header="Content-Type: （複数あり・要確認）")
    schema = from_run_case(case)
    assert schema.expected_content_type is None


def test_response_time_3s():
    schema = from_run_case(make_case(expected_response_time="3秒以内"))
    assert schema.expected_response_time_ms == pytest.approx(3000.0)


def test_response_time_1s():
    schema = from_run_case(make_case(expected_response_time="1秒以内"))
    assert schema.expected_response_time_ms == pytest.approx(1000.0)


def test_response_time_default_when_empty():
    schema = from_run_case(make_case(expected_response_time=""))
    assert schema.expected_response_time_ms == pytest.approx(3000.0)
