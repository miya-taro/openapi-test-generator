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


def test_derive_response_header_includes_header_names_existence_only():
    result = _derive_response_header(
        {"contentTypes": ["application/json"], "headers": {"X-Total-Count": {"required": True}}}
    )
    assert "X-Total-Count: （存在確認のみ）" in result


def test_derive_response_header_does_not_require_optional_header():
    result = _derive_response_header(
        {"contentTypes": ["application/json"], "headers": {"X-Trace": {"schema": {"type": "string"}}}}
    )
    assert "X-Trace" not in result


def test_derive_response_header_does_not_treat_example_as_fixed_contract_value():
    result = _derive_response_header(
        {"contentTypes": ["application/json"], "headers": {"X-Api-Version": {
            "required": True, "example": "v1",
        }}}
    )
    assert "X-Api-Version: （存在確認のみ）" in result


def test_derive_response_header_does_not_treat_default_as_fixed_contract_value():
    result = _derive_response_header(
        {"contentTypes": ["application/json"], "headers": {
            "X-Mode": {"required": True, "schema": {"type": "string", "default": "safe"}},
        }}
    )
    assert "X-Mode: （存在確認のみ）" in result


def test_derive_response_header_uses_schema_enum_of_one_when_available():
    result = _derive_response_header(
        {
            "contentTypes": ["application/json"],
            "headers": {"X-Cache-Status": {"required": True, "schema": {"enum": ["HIT"]}}},
        }
    )
    assert "X-Cache-Status: HIT" in result


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


def test_generate_test_cases_emits_documented_unsupported_content_type_case():
    spec = {
        "operationId": "createUser", "path": "/users", "method": "POST",
        "in": "header", "name": "Content-Type", "required": True,
        "schema": {}, "successStatus": "415",
        "responsesInfo": {"415": {"contentTypes": ["application/json"], "headers": {}}},
        "unsupportedContentType": "text/plain",
    }
    cases = generate_test_cases([spec], [], ALL_OPTS)
    assert len(cases) == 2
    assert cases[1]["inputValue"] == "（省略）"
    assert cases[0]["paramName"] == "Content-Type"
    assert cases[0]["inputValue"] == "text/plain"
    assert cases[0]["expectedStatus"] == "4xx"
    assert "定義済みヘッダ" in cases[0]["expectedResponseHeader"]


def test_generate_test_cases_omits_unsupported_content_type_case_when_abnormal_disabled():
    spec = {
        "operationId": "createUser", "path": "/users", "method": "POST",
        "in": "header", "name": "Content-Type", "required": True,
        "schema": {}, "successStatus": "415", "responsesInfo": {},
        "unsupportedContentType": "text/plain",
    }
    cases = generate_test_cases([spec], [], {**ALL_OPTS, "includeAbnormal": False})
    assert cases == []


def test_generate_test_cases_includes_operation_baseline_normal_case():
    operation = {
        "operationBaseline": True,
        "operationId": "createUser",
        "path": "/users",
        "method": "POST",
        "successStatus": "2xx",
        "responsesInfo": {"201": {"contentTypes": ["application/json"], "headers": {}}},
    }

    cases = generate_test_cases([operation], [], ALL_OPTS)

    assert len(cases) == 1
    assert cases[0]["in"] == "operation"
    assert cases[0]["paramName"] == "__valid_request__"
    assert cases[0]["keyword"] == "request"
    assert cases[0]["perspective"] == "正常系_最小有効リクエスト"
    assert cases[0]["expectedStatus"] == "2xx"


def test_generate_test_cases_omits_operation_baseline_when_normal_disabled():
    operation = {
        "operationBaseline": True,
        "operationId": "getUser",
        "path": "/users/{id}",
        "method": "GET",
        "successStatus": "2xx",
        "responsesInfo": {},
    }

    cases = generate_test_cases([operation], [], {**ALL_OPTS, "includeNormal": False})

    assert cases == []


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


def test_generate_from_schema_type_array_null_first_still_routes_to_integer_rules():
    # OAS 3.1 の type 配列は順不同（"null" を先頭に書いても文法上正当）。
    # type[0] だけを見て振り分けると、この並びでは "integer" を見逃し、
    # minimum/maximum の境界値ケースが1件も生成されなくなる回帰テスト。
    cases = _generate_from_schema(
        {"type": ["null", "integer"], "minimum": 1, "maximum": 100}, False, "query", "age", ALL_OPTS, "200"
    )
    assert any(c["keyword"] == "minimum" for c in cases)
    assert any(c["keyword"] == "maximum" for c in cases)


def test_generate_from_schema_type_array_null_first_still_routes_to_array_rules():
    cases = _generate_from_schema(
        {"type": ["null", "array"], "minItems": 1, "maxItems": 5, "items": {"type": "string"}},
        False, "query", "tags", ALL_OPTS, "200",
    )
    assert any(c["keyword"] == "minItems" for c in cases)
    assert any(c["keyword"] == "maxItems" for c in cases)


def test_generate_from_schema_type_array_all_null_generates_no_type_specific_cases():
    # "null" 以外の型が無い場合はどのルールにも振り分けない（何も推測しようがない）。
    # common.py 由来の optional/nullable ケースは type 不問で生成されるため対象外。
    cases = _generate_from_schema({"type": ["null"]}, False, "query", "x", ALL_OPTS, "200")
    assert all(c["keyword"] in ("optional", "nullable") for c in cases)
