from src.generator.rules.object import generate_object_cases

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
ABNORMAL_ONLY = {"includeNormal": False, "includeAbnormal": True, "enumFullCoverage": False}
NORMAL_ONLY = {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}


def test_additional_properties_false_generates_abnormal_case():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": False},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    case = next(c for c in cases if c["keyword"] == "additionalProperties")
    assert case["expectedStatus"] == "400"
    assert case["perspective"] == "異常系_additionalProperties"


def test_additional_properties_not_false_no_case():
    cases = generate_object_cases(
        {"type": "object"}, {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True}
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)


def test_empty_body_when_root_and_required_fields_exist():
    cases = generate_object_cases(
        {"type": "object", "required": ["name"]},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    case = next(c for c in cases if c["perspective"] == "異常系_空body")
    assert case["inputValue"] == "{}"
    assert case["expectedStatus"] == "400"


def test_no_empty_body_case_when_not_root_body():
    cases = generate_object_cases(
        {"type": "object", "required": ["name"]},
        {"paramName": "address", "opts": ALL_OPTS, "isRootBody": False},
    )
    assert not any(c["perspective"] == "異常系_空body" for c in cases)


def test_no_empty_body_case_when_no_required_fields():
    cases = generate_object_cases(
        {"type": "object", "required": []}, {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True}
    )
    assert not any(c["perspective"] == "異常系_空body" for c in cases)


def test_normal_only_generates_nothing():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": False, "required": ["name"]},
        {"paramName": "requestBody", "opts": NORMAL_ONLY, "isRootBody": True},
    )
    assert cases == []
