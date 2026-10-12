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
    assert case["expectedStatus"] == "4xx"
    assert case["perspective"] == "異常系_additionalProperties"


def test_additional_properties_unspecified_does_not_generate_extra_prop_case():
    cases = generate_object_cases(
        {"type": "object"}, {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True}
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)


def test_additional_properties_unspecified_normal_only_does_not_generate_extra_prop_case():
    cases = generate_object_cases(
        {"type": "object"}, {"paramName": "requestBody", "opts": NORMAL_ONLY, "isRootBody": True}
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)


def test_additional_properties_unspecified_abnormal_only_generates_nothing():
    # 未指定の場合は追加プロパティ用のケースを作らない。
    cases = generate_object_cases(
        {"type": "object"}, {"paramName": "requestBody", "opts": ABNORMAL_ONLY, "isRootBody": True}
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)


def test_empty_body_when_root_and_required_fields_exist():
    cases = generate_object_cases(
        {"type": "object", "required": ["name"]},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    case = next(c for c in cases if c["perspective"] == "異常系_空body")
    assert case["inputValue"] == "{}"
    assert case["expectedStatus"] == "4xx"


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


# --- additionalProperties がスキーマ（型付き追加プロパティを許可）の場合 ---


def test_additional_properties_schema_does_not_generate_extra_prop_normal_case():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True, "successStatus": "201"},
    )
    assert not any(c["perspective"] == "正常系_additionalProperties型適合" for c in cases)


def test_additional_properties_schema_generates_abnormal_case_with_mismatched_type():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": {"type": "integer"}},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    case = next(c for c in cases if c["perspective"] == "異常系_additionalProperties型不適合")
    assert case["expectedStatus"] == "4xx"
    assert '"abc"' in case["inputValue"]


def test_additional_properties_schema_normal_only_skips_abnormal_case():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": {"type": "integer"}},
        {"paramName": "requestBody", "opts": NORMAL_ONLY, "isRootBody": True},
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)


def test_additional_properties_schema_abnormal_only_skips_normal_case():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": {"type": "integer"}},
        {"paramName": "requestBody", "opts": ABNORMAL_ONLY, "isRootBody": True},
    )
    assert not any(c["perspective"] == "正常系_additionalProperties型適合" for c in cases)
    assert any(c["perspective"] == "異常系_additionalProperties型不適合" for c in cases)


def test_additional_properties_string_rejects_numeric_value():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    abnormal = next(c for c in cases if c["perspective"] == "異常系_additionalProperties型不適合")
    assert ": 123" in abnormal["inputValue"]


def test_additional_properties_true_does_not_generate_extra_prop_case():
    cases = generate_object_cases(
        {"type": "object", "additionalProperties": True},
        {"paramName": "requestBody", "opts": ALL_OPTS, "isRootBody": True},
    )
    assert not any(c["keyword"] == "additionalProperties" for c in cases)
