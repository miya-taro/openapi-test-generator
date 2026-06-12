import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from excel_reader import read_excel
from models import RunCase

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xlsx"


def test_read_returns_list_of_run_cases():
    cases = read_excel(FIXTURE)
    assert len(cases) == 3
    assert all(isinstance(c, RunCase) for c in cases)


def test_first_case_fields():
    cases = read_excel(FIXTURE)
    c = cases[0]
    assert c.id == "TC-001-001"
    assert c.operation_id == "getUsers"
    assert c.path == "/users"
    assert c.method == "GET"
    assert c.param_in == "query"
    assert c.param_name == "page"
    assert c.input_value == "1"
    assert c.expected_status == "200"
    assert c.expected_response_body == "OpenAPI定義のJSON schemaに従うこと"
    assert c.expected_response_time == "3秒以内"


def test_missing_optional_field_defaults_to_empty_string():
    cases = read_excel(FIXTURE)
    # TC-001-002 has empty expected_response_body and header
    c = cases[1]
    assert c.expected_response_body == ""
    assert c.expected_response_header == ""


def test_third_case_is_post():
    cases = read_excel(FIXTURE)
    c = cases[2]
    assert c.method == "POST"
    assert c.param_in == "body"
    assert c.expected_status == "201"
