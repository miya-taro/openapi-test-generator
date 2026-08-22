from src.generator.rules.common import generate_common_cases

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}


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
