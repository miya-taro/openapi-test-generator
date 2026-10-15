import src.generator.rules.string as string_rule
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
    assert abnormal["expectedStatus"] == "4xx"


def test_email_max_length_keeps_the_format_valid():
    cases = generate_string_cases(
        {"type": "string", "format": "email", "maxLength": 254},
        {"paramName": "email", "opts": ALL_OPTS},
    )
    normal = next(c for c in cases if c["keyword"] == "maxLength" and c["perspective"].startswith("正常系"))
    assert len(normal["inputValue"]) == 254
    assert normal["inputValue"].count("@") == 1
    local, domain = normal["inputValue"].split("@")
    assert len(local) <= 64
    assert all(1 <= len(label) <= 63 for label in domain.split("."))
    assert len(domain.split(".")[-1]) >= 2


def test_email_max_length_abnormal_case_keeps_format_valid():
    cases = generate_string_cases(
        {"type": "string", "format": "email", "maxLength": 253},
        {"paramName": "email", "opts": ALL_OPTS},
    )
    abnormal = next(c for c in cases if c["keyword"] == "maxLength" and c["perspective"].startswith("異常系"))
    assert len(abnormal["inputValue"]) == 254
    assert abnormal["inputValue"].count("@") == 1


def test_email_max_length_abnormal_case_is_omitted_when_format_would_also_fail():
    cases = generate_string_cases(
        {"type": "string", "format": "email", "maxLength": 254},
        {"paramName": "email", "opts": ALL_OPTS},
    )
    assert not any(
        c["keyword"] == "maxLength" and c["perspective"].startswith("異常系")
        for c in cases
    )


def test_email_format_case_respects_tight_length_constraints():
    cases = generate_string_cases(
        {"type": "string", "format": "email", "maxLength": 13},
        {"paramName": "email", "opts": ALL_OPTS},
    )
    normal = next(c for c in cases if c["keyword"] == "format" and c["perspective"].startswith("正常系"))
    assert len(normal["inputValue"]) <= 13
    assert "@" in normal["inputValue"]


def test_normal_max_length_case_respects_enum():
    cases = generate_string_cases(
        {"type": "string", "enum": ["one", "two"], "maxLength": 5},
        {"paramName": "value", "opts": ALL_OPTS},
    )
    assert not any(
        c["keyword"] == "maxLength" and c["perspective"].startswith("正常系")
        for c in cases
    )


def test_normal_format_case_respects_enum():
    cases = generate_string_cases(
        {"type": "string", "format": "email", "enum": ["not-an-email"]},
        {"paramName": "email", "opts": ALL_OPTS},
    )
    assert not any(
        c["keyword"] == "format" and c["perspective"].startswith("正常系")
        for c in cases
    )


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
    assert abnormal["expectedStatus"] == "4xx"


def test_invalid_format_case_respects_length_constraints():
    cases = generate_string_cases(
        {"type": "string", "format": "date", "maxLength": 8},
        {"paramName": "date", "opts": ALL_OPTS},
    )
    assert not any(
        c["keyword"] == "format" and c["perspective"].startswith("異常系")
        for c in cases
    )


def test_format_unknown_generates_no_cases():
    cases = generate_string_cases({"type": "string", "format": "unknown-fmt"}, {"paramName": "d", "opts": ALL_OPTS})
    assert not any(c["keyword"] == "format" for c in cases)


def test_format_binary_is_skipped():
    cases = generate_string_cases({"type": "string", "format": "binary"}, {"paramName": "f", "opts": ALL_OPTS})
    assert not any(c["keyword"] == "format" for c in cases)


# --- pattern: 単純パターンの手書き逆生成 ---


def test_pattern_simple_digit_form():
    cases = generate_string_cases({"type": "string", "pattern": "^[0-9]{5}$"}, {"paramName": "code", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "11111"
    assert normal["notes"] == ""
    assert abnormal["inputValue"] == "__BAD_PATTERN__"


def test_pattern_simple_alpha_form():
    cases = generate_string_cases(
        {"type": "string", "pattern": "^[a-zA-Z]{3}$"}, {"paramName": "code", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("正常系"))
    assert normal["inputValue"] == "aaa"


def test_pattern_simple_alnum_range_form():
    cases = generate_string_cases(
        {"type": "string", "pattern": "^[a-z0-9]{3,10}$"}, {"paramName": "code", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("正常系"))
    assert normal["inputValue"] == "aaa"


# --- pattern: rstr 経由の逆生成 ---


def test_pattern_complex_form_uses_rstr():
    cases = generate_string_cases(
        {"type": "string", "pattern": "^[A-Z]{2}-[0-9]{4}$"}, {"paramName": "code", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("正常系"))
    import re
    assert re.search(r"^[A-Z]{2}-[0-9]{4}$", normal["inputValue"])
    assert normal["notes"] == ""


def test_pattern_rstr_unavailable_skips_automated_normal_case(monkeypatch):
    monkeypatch.setattr("src.pattern_samples.Rstr", None)
    cases = generate_string_cases(
        {"type": "string", "pattern": "^[A-Z]{2}-[0-9]{4}$"}, {"paramName": "code", "opts": ALL_OPTS}
    )
    assert not any(c["keyword"] == "pattern" and c["perspective"].startswith("正常系") for c in cases)
    assert any(c["keyword"] == "pattern" and c["perspective"].startswith("異常系") for c in cases)


def test_pattern_rstr_raises_skips_automated_normal_case(monkeypatch):
    def _boom(_pattern):
        raise ValueError("boom")

    monkeypatch.setattr(string_rule, "pattern_samples", _boom)
    cases = generate_string_cases(
        {"type": "string", "pattern": "^[A-Z]{2}-[0-9]{4}$"}, {"paramName": "code", "opts": ALL_OPTS}
    )
    assert not any(c["keyword"] == "pattern" and c["perspective"].startswith("正常系") for c in cases)


def test_pattern_abnormal_case_is_guaranteed_to_miss_pattern():
    import re

    cases = generate_string_cases(
        {"type": "string", "pattern": "^[A-Za-z ]+$"}, {"paramName": "name", "opts": ALL_OPTS}
    )
    abnormal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("異常系"))
    assert re.search(r"^[A-Za-z ]+$", abnormal["inputValue"]) is None


def test_pattern_abnormal_case_is_omitted_when_no_mismatch_exists():
    cases = generate_string_cases(
        {"type": "string", "pattern": ".*"}, {"paramName": "text", "opts": ALL_OPTS}
    )
    assert not any(c["keyword"] == "pattern" and c["perspective"].startswith("異常系") for c in cases)


def test_pattern_case_respects_other_string_constraints():
    cases = generate_string_cases(
        {"type": "string", "pattern": "^x+$", "minLength": 3, "maxLength": 5},
        {"paramName": "text", "opts": ALL_OPTS},
    )
    normal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "pattern" and c["perspective"].startswith("異常系"))
    assert 3 <= len(normal["inputValue"]) <= 5
    assert 3 <= len(abnormal["inputValue"]) <= 5


def test_pattern_normal_only_no_abnormal_case():
    opts = {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}
    cases = generate_string_cases({"type": "string", "pattern": "^[0-9]{3}$"}, {"paramName": "code", "opts": opts})
    assert not any(c["perspective"].startswith("異常系") for c in cases)
