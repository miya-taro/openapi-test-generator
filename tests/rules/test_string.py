from src.generator.rules.string import generate_string_cases

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
FULL_ENUM_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": True}


def test_enum_default_representative_and_abnormal():
    cases = generate_string_cases(
        {"type": "string", "enum": ["active", "inactive", "deleted"]}, {"paramName": "status", "opts": ALL_OPTS}
    )
    normal = [c for c in cases if c["perspective"].startswith("正常系")]
    abnormal = [c for c in cases if c["perspective"].startswith("異常系")]
    assert len(normal) == 1
    assert normal[0]["inputValue"] == "active"
    assert len(abnormal) == 1
    assert abnormal[0]["inputValue"] == "__INVALID__"


def test_enum_full_coverage():
    cases = generate_string_cases(
        {"type": "string", "enum": ["a", "b", "c"]}, {"paramName": "x", "opts": FULL_ENUM_OPTS}
    )
    normal = [c for c in cases if c["perspective"].startswith("正常系")]
    assert len(normal) == 3


def test_max_length():
    cases = generate_string_cases({"type": "string", "maxLength": 5}, {"paramName": "s", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "maxLength" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "maxLength" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "aaaaa"
    assert abnormal["inputValue"] == "aaaaaa"


def test_min_length_zero_no_abnormal():
    cases = generate_string_cases({"type": "string", "minLength": 0}, {"paramName": "s", "opts": ALL_OPTS})
    abnormal = [c for c in cases if c["keyword"] == "minLength" and c["perspective"].startswith("異常系")]
    assert len(abnormal) == 0


def test_min_length_positive():
    cases = generate_string_cases({"type": "string", "minLength": 3}, {"paramName": "s", "opts": ALL_OPTS})
    abnormal = next(c for c in cases if c["keyword"] == "minLength" and c["perspective"].startswith("異常系"))
    assert abnormal["inputValue"] == "aa"


def test_format_date_samples():
    cases = generate_string_cases({"type": "string", "format": "date"}, {"paramName": "d", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "format" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "format" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "2024-01-01"
    assert abnormal["inputValue"] == "not-a-date"
