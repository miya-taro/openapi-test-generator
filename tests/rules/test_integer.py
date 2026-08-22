from src.generator.rules.integer import generate_integer_cases

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
NORMAL_ONLY = {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}
ABNORMAL_ONLY = {"includeNormal": False, "includeAbnormal": True, "enumFullCoverage": False}


def test_minimum_only_normal_and_abnormal():
    cases = generate_integer_cases({"type": "integer", "minimum": 5}, {"paramName": "n", "opts": ALL_OPTS})
    assert len(cases) == 2
    assert cases[0]["inputValue"] == "5"
    assert cases[1]["inputValue"] == "4"


def test_maximum_only_normal_and_abnormal():
    cases = generate_integer_cases({"type": "integer", "maximum": 100}, {"paramName": "n", "opts": ALL_OPTS})
    assert len(cases) == 2
    assert cases[0]["inputValue"] == "100"
    assert cases[1]["inputValue"] == "101"


def test_minimum_and_maximum_five_cases():
    cases = generate_integer_cases(
        {"type": "integer", "minimum": 0, "maximum": 100}, {"paramName": "n", "opts": ALL_OPTS}
    )
    assert len(cases) == 5
    mid_case = next(c for c in cases if c["keyword"] == "minimum+maximum")
    assert mid_case["inputValue"] == "50"


def test_abnormal_only():
    cases = generate_integer_cases(
        {"type": "integer", "minimum": 1, "maximum": 10}, {"paramName": "n", "opts": ABNORMAL_ONLY}
    )
    assert all(c["perspective"].startswith("異常系") for c in cases)


def test_normal_only():
    cases = generate_integer_cases(
        {"type": "integer", "minimum": 1, "maximum": 10}, {"paramName": "n", "opts": NORMAL_ONLY}
    )
    assert all(c["perspective"].startswith("正常系") for c in cases)


def test_exclusive_minimum_value():
    cases = generate_integer_cases(
        {"type": "integer", "_exclusiveMinimumValue": 10}, {"paramName": "n", "opts": ALL_OPTS}
    )
    abnormal = next(c for c in cases if "exclusiveMinimum境界値" in c["perspective"])
    normal = next(c for c in cases if "exclusiveMinimum超過値" in c["perspective"])
    assert abnormal["inputValue"] == "10"
    assert normal["inputValue"] == "11"


def test_multiple_of():
    cases = generate_integer_cases({"type": "integer", "multipleOf": 3}, {"paramName": "n", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "multipleOf" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "multipleOf" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "6"
    assert abnormal["inputValue"] == "4"
