from src.generator import generate_test_cases, _derive_response_body, _derive_response_header, _generate_from_schema

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
ABNORMAL_ONLY = {"includeNormal": False, "includeAbnormal": True, "enumFullCoverage": False}


# --- _derive_response_body ---


def test_derive_response_body_none_info():
    assert _derive_response_body(None) == ""


def test_derive_response_body_no_content_types():
    assert _derive_response_body({"contentTypes": [], "headerNames": []}) == "レスポンスボディなし"


def test_derive_response_body_application_json():
    result = _derive_response_body({"contentTypes": ["application/json"], "headerNames": []})
    assert result == "OpenAPI定義のJSON schemaに従うこと"


def test_derive_response_body_single_non_json_content_type():
    result = _derive_response_body({"contentTypes": ["application/pdf"], "headerNames": []})
    assert result == "application/pdf に従うレスポンスを返すこと"


def test_derive_response_body_multiple_content_types():
    result = _derive_response_body({"contentTypes": ["application/pdf", "text/csv"], "headerNames": []})
    assert result == "OpenAPIレスポンス定義を確認すること"


# --- _derive_response_header ---


def test_derive_response_header_none_info():
    assert _derive_response_header(None) == ""


def test_derive_response_header_single_content_type():
    result = _derive_response_header({"contentTypes": ["application/json"], "headerNames": []})
    assert result == "Content-Type: application/json"


def test_derive_response_header_multiple_content_types():
    result = _derive_response_header({"contentTypes": ["application/json", "text/csv"], "headerNames": []})
    assert "複数あり" in result


def test_derive_response_header_includes_header_names():
    result = _derive_response_header({"contentTypes": ["application/json"], "headerNames": ["X-Total-Count"]})
    assert "X-Total-Count: OpenAPI定義を確認" in result


# --- generate_test_cases: auth の includeAbnormal 制御 ---


def _auth_spec():
    return {
        "operationId": "getMe",
        "path": "/me",
        "method": "GET",
        "schemeType": "bearer",
        "headerName": "Authorization",
        "successStatus": "200",
        "responsesInfo": {},
    }


def test_generate_test_cases_skips_auth_when_abnormal_excluded():
    opts = {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}
    cases = generate_test_cases([], [], opts, [_auth_spec()])
    assert cases == []


def test_generate_test_cases_includes_auth_when_abnormal_enabled():
    cases = generate_test_cases([], [], ABNORMAL_ONLY, [_auth_spec()])
    assert len(cases) == 2
    assert all(c["keyword"] == "auth" for c in cases)
    assert all(c["expectedResponseBody"] == "" for c in cases)


# --- _generate_from_schema: 型ごとのルーティング ---


def test_generate_from_schema_routes_array_type():
    cases = _generate_from_schema(
        {"type": "array", "minItems": 1}, False, "body", "tags", ALL_OPTS, "200"
    )
    assert any(c["keyword"] == "minItems" for c in cases)


def test_generate_from_schema_unknown_type_with_format_falls_back_to_string_rules():
    cases = _generate_from_schema(
        {"format": "email"}, False, "query", "email", ALL_OPTS, "200"
    )
    assert any(c["keyword"] == "format" for c in cases)


def test_generate_from_schema_unknown_type_without_hints_generates_no_string_rule_cases():
    # 共通ルール(required/type)は type 不問で動くため optional ケースは残るが、
    # string.py 由来のケース（enum/format/pattern等）は生成されない
    cases = _generate_from_schema({}, False, "query", "x", ALL_OPTS, "200")
    assert all(c["keyword"] == "optional" for c in cases)
