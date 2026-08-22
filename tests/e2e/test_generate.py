from pathlib import Path

from src.parser import parse_openapi
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids

FIXTURE = str(Path(__file__).resolve().parent / "fixtures" / "simple.openapi.json")

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}


def _generate():
    api = parse_openapi(FIXTURE)
    param_specs, body_specs = extract_specs(api)
    raw_cases = generate_test_cases(param_specs, body_specs, ALL_OPTS)
    return assign_ids(raw_cases)


def test_parse_extract_generate_assign_succeeds():
    cases = _generate()
    assert len(cases) > 0
    assert all(c["id"].startswith("TC-") for c in cases)


def test_get_user_id_param_has_minimum_and_maximum_cases():
    cases = _generate()
    get_user_cases = [c for c in cases if c["operationId"] == "getUser" and c["paramName"] == "id"]
    assert any(c["keyword"] == "minimum" for c in get_user_cases)
    assert any(c["keyword"] == "maximum" for c in get_user_cases)


def test_get_user_status_param_has_enum_case():
    cases = _generate()
    status_cases = [c for c in cases if c["operationId"] == "getUser" and c["paramName"] == "status"]
    assert any(c["keyword"] == "enum" for c in status_cases)


def test_create_user_has_empty_body_abnormal_case():
    cases = _generate()
    empty_cases = [
        c for c in cases if c["operationId"] == "createUser" and c["perspective"] == "異常系_空body"
    ]
    assert len(empty_cases) == 1


def test_all_case_ids_are_unique():
    cases = _generate()
    ids = [c["id"] for c in cases]
    assert len(set(ids)) == len(ids)
