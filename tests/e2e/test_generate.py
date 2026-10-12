import json
from pathlib import Path

from src.parser import parse_openapi
from src.extractor import extract_auth_specs, extract_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.security_payload import AUTH_NONE_MARKER, OPENAPI_SECURITY_PARAM, parse_security_payload

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


def test_login_cases_do_not_add_unconfigured_extra_property(tmp_path):
    source = {
        "openapi": "3.1.0",
        "info": {"title": "login fixture", "version": "1"},
        "paths": {"/v1/auth/login": {"post": {
            "operationId": "login",
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"user": {"type": "string", "example": "test"}},
                "required": ["user"],
            }}}},
            "responses": {"200": {"description": "OK"}, "400": {"description": "Invalid"}},
        }}},
    }
    path = tmp_path / "login.openapi.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    params, bodies = extract_specs(parse_openapi(str(path)))
    cases = generate_test_cases(params, bodies, ALL_OPTS)

    assert any(case["perspective"] == "正常系_最小有効リクエスト" for case in cases)
    assert not any("__extra__" in case.get("inputValue", "") for case in cases)


def test_openapi_auth_alternatives_flow_into_identified_test_cases(tmp_path):
    source = {
        "openapi": "3.1.0",
        "info": {"title": "auth fixture", "version": "1"},
        "components": {"securitySchemes": {
            "BearerAuth": {"type": "http", "scheme": "bearer"},
            "QueryKey": {"type": "apiKey", "in": "query", "name": "api_key"},
            "CookieKey": {"type": "apiKey", "in": "cookie", "name": "session_key"},
        }},
        "paths": {"/me": {"get": {
            "operationId": "getMe",
            "security": [{"BearerAuth": []}, {"QueryKey": [], "CookieKey": []}],
            "responses": {
                "200": {"description": "OK"},
                "403": {"description": "Forbidden"},
            },
        }}},
    }
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(source), encoding="utf-8")

    api = parse_openapi(str(openapi_path))
    auth_specs = extract_auth_specs(api)
    cases = assign_ids(generate_test_cases([], [], ALL_OPTS, auth_specs))

    assert [case["id"] for case in cases] == ["TC-getMe-001", "TC-getMe-002"]
    assert all(case["paramName"] == OPENAPI_SECURITY_PARAM for case in cases)
    assert [case["inputValue"] for case in cases][0] == AUTH_NONE_MARKER
    assert [case["expectedStatus"] for case in cases] == ["403", "403"]
    assert parse_security_payload(cases[1]["inputValue"]) == {
        "headers": {"Authorization": "invalid-token-xxx"},
        "query": {"api_key": "invalid-token-xxx"},
        "cookies": {"session_key": "invalid-token-xxx"},
    }
