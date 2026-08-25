from src.generator.rules.common import (
    generate_common_cases,
    generate_one_of_variant_cases,
    ONE_OF_VARIANT_MARKER_PREFIX,
)

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
ONE_OF_OPTS = {**ALL_OPTS, "oneOfFullCoverage": True}

_VARIANTS_SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "_oneOfVariants": [
        {"type": "object", "properties": {"name": {"type": "string"}}},
        {"type": "object", "properties": {"email": {"type": "string"}}},
        {"type": "object", "properties": {"phone": {"type": "string"}}},
    ],
}


def _root_body_ctx(opts) -> dict:
    return {"paramIn": "body", "paramName": "requestBody", "opts": opts, "successStatus": "200", "isRootBody": True}


def test_one_of_variant_cases_disabled_by_default():
    cases = generate_one_of_variant_cases(_VARIANTS_SCHEMA, _root_body_ctx(ALL_OPTS))
    assert cases == []


def test_one_of_variant_cases_generated_when_flag_enabled():
    cases = generate_one_of_variant_cases(_VARIANTS_SCHEMA, _root_body_ctx(ONE_OF_OPTS))
    # インデックス0（代表バリアント）は通常ケースで既にカバー済みなので、1・2番目のみ追加
    assert len(cases) == 2
    assert all(c["perspective"].startswith("正常系") for c in cases)
    assert cases[0]["inputValue"] == f"{ONE_OF_VARIANT_MARKER_PREFIX}1"
    assert cases[1]["inputValue"] == f"{ONE_OF_VARIANT_MARKER_PREFIX}2"


def test_one_of_variant_cases_skipped_when_not_root_body():
    ctx = {"paramIn": "body", "paramName": "user.contact", "opts": ONE_OF_OPTS, "successStatus": "200", "isRootBody": False}
    cases = generate_one_of_variant_cases(_VARIANTS_SCHEMA, ctx)
    assert cases == []


def test_one_of_variant_cases_skipped_when_no_variants():
    cases = generate_one_of_variant_cases({"type": "object"}, _root_body_ctx(ONE_OF_OPTS))
    assert cases == []


def test_one_of_variant_cases_respects_include_normal_false():
    ctx = _root_body_ctx({**ONE_OF_OPTS, "includeNormal": False})
    cases = generate_one_of_variant_cases(_VARIANTS_SCHEMA, ctx)
    assert cases == []


def test_required_true_query_missing_400():
    cases = generate_common_cases(
        {"type": "string"}, True, {"paramIn": "query", "paramName": "name", "opts": ALL_OPTS}
    )
    required_case = next(c for c in cases if c["keyword"] == "required")
    assert required_case["expectedStatus"] == "400"


def test_required_true_path_missing_404():
    cases = generate_common_cases(
        {"type": "string"}, True, {"paramIn": "path", "paramName": "id", "opts": ALL_OPTS}
    )
    required_case = next(c for c in cases if c["keyword"] == "required")
    assert required_case["expectedStatus"] == "404"


def test_required_false_no_missing_case():
    cases = generate_common_cases(
        {"type": "string"}, False, {"paramIn": "query", "paramName": "name", "opts": ALL_OPTS}
    )
    assert not any(c["keyword"] == "required" for c in cases)


def test_type_integer_invalid_value_is_abc():
    cases = generate_common_cases(
        {"type": "integer"}, False, {"paramIn": "query", "paramName": "count", "opts": ALL_OPTS}
    )
    type_case = next(c for c in cases if c["keyword"] == "type")
    assert type_case["inputValue"] == '"abc"'


def test_nullable_true_generates_normal_null_case():
    cases = generate_common_cases(
        {"type": "string", "nullable": True}, False, {"paramIn": "query", "paramName": "note", "opts": ALL_OPTS}
    )
    null_case = next(c for c in cases if c["keyword"] == "nullable")
    assert null_case["perspective"] == "正常系_null許容"
    assert null_case["inputValue"] == "null"


def test_oas31_null_in_type_array_generates_normal_null_case():
    cases = generate_common_cases(
        {"type": ["string", "null"]}, False, {"paramIn": "query", "paramName": "note", "opts": ALL_OPTS}
    )
    null_case = next(c for c in cases if c["keyword"] == "nullable")
    assert null_case["perspective"] == "正常系_null許容"


def test_not_nullable_generates_abnormal_null_case():
    cases = generate_common_cases(
        {"type": "string"}, False, {"paramIn": "query", "paramName": "note", "opts": ALL_OPTS}
    )
    null_case = next(c for c in cases if c["keyword"] == "nullable")
    assert null_case["perspective"] == "異常系_null不可"
    assert null_case["expectedStatus"] == "400"


def test_no_nullable_case_when_type_missing():
    cases = generate_common_cases({}, False, {"paramIn": "query", "paramName": "note", "opts": ALL_OPTS})
    assert not any(c["keyword"] == "nullable" for c in cases)
