import json

from src.generator.rules.auth import generate_auth_cases


def _spec(scheme_type: str, header_name: str = "Authorization") -> dict:
    return {
        "operationId": "getUser",
        "path": "/users/{id}",
        "method": "GET",
        "schemeType": scheme_type,
        "headerName": header_name,
        "successStatus": "200",
        "responsesInfo": {},
    }


def test_generates_two_cases_no_auth_and_invalid_token():
    cases = generate_auth_cases(_spec("bearer"))
    assert len(cases) == 2
    assert cases[0]["perspective"] == "異常系_認証なし"
    assert cases[0]["expectedStatus"] == "401"
    assert cases[1]["perspective"] == "異常系_無効トークン"
    assert cases[1]["expectedStatus"] == "401"


def test_bearer_invalid_token_value():
    cases = generate_auth_cases(_spec("bearer"))
    assert json.loads(cases[1]["inputValue"]) == {
        "headers": {"Authorization": "invalid-token-xxx"},
        "query": {},
        "cookies": {},
    }


def test_basic_invalid_token_value():
    cases = generate_auth_cases(_spec("basic"))
    assert json.loads(cases[1]["inputValue"])["headers"]["Authorization"] == "invalid-token-xxx"


def test_api_key_invalid_token_value():
    cases = generate_auth_cases(_spec("apiKey", "X-Api-Key"))
    assert json.loads(cases[1]["inputValue"])["headers"]["X-Api-Key"] == "invalid-token-xxx"
    assert "X-Api-Key" in cases[1]["notes"]


def test_no_auth_case_omits_header():
    cases = generate_auth_cases(_spec("bearer"))
    assert cases[0]["paramName"] == "__openapi_security__"
    assert cases[0]["inputValue"] == "（認証ヘッダなし）"


def test_multiple_security_schemes_generate_one_invalid_bundle_for_all_credentials():
    spec = _spec("bearer")
    spec["securitySchemes"] = [
        {"schemeName": "BearerAuth", "schemeType": "bearer", "in": "header", "name": "Authorization"},
        {"schemeName": "QueryKey", "schemeType": "apiKey", "in": "query", "name": "api_key"},
        {"schemeName": "CookieKey", "schemeType": "apiKey", "in": "cookie", "name": "session_key"},
    ]

    cases = generate_auth_cases(spec)

    assert len(cases) == 2
    assert cases[0]["paramName"] == "__openapi_security__"
    assert cases[1]["paramName"] == "__openapi_security__"
    assert json.loads(cases[1]["inputValue"]) == {
        "headers": {"Authorization": "invalid-token-xxx"},
        "query": {"api_key": "invalid-token-xxx"},
        "cookies": {"session_key": "invalid-token-xxx"},
    }
    assert "BearerAuth" in cases[1]["notes"] and "CookieKey" in cases[1]["notes"]


def test_auth_failure_expectation_uses_documented_403_when_401_is_absent():
    spec = _spec("bearer")
    spec["responsesInfo"] = {"200": {}, "403": {}}

    cases = generate_auth_cases(spec)

    assert [case["expectedStatus"] for case in cases] == ["403", "403"]
