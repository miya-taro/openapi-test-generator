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
    assert cases[1]["inputValue"] == "Bearer invalid-token-xxx"


def test_basic_invalid_token_value():
    cases = generate_auth_cases(_spec("basic"))
    assert cases[1]["inputValue"] == "Basic aW52YWxpZA=="


def test_api_key_invalid_token_value():
    cases = generate_auth_cases(_spec("apiKey", "X-Api-Key"))
    assert cases[1]["inputValue"] == "invalid-token-xxx"
    assert "X-Api-Key" in cases[1]["notes"]


def test_no_auth_case_omits_header():
    cases = generate_auth_cases(_spec("bearer"))
    assert cases[0]["inputValue"] == "（認証ヘッダなし）"
