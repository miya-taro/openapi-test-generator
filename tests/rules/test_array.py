from src.generator.rules.array import generate_array_cases

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}


def test_min_items():
    cases = generate_array_cases(
        {"type": "array", "minItems": 2, "items": {"type": "string"}}, {"paramName": "tags", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == '["a", "a"]'
    assert abnormal["inputValue"] == '["a"]'


def test_max_items():
    cases = generate_array_cases(
        {"type": "array", "maxItems": 3, "items": {"type": "integer"}}, {"paramName": "ids", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "maxItems" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "maxItems" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "[1, 1, 1]"
    assert abnormal["inputValue"] == "[1, 1, 1, 1]"


def test_unique_items():
    cases = generate_array_cases(
        {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        {"paramName": "tags", "opts": ALL_OPTS},
    )
    abnormal = next(c for c in cases if c["keyword"] == "uniqueItems")
    assert "異常系" in abnormal["perspective"]
    assert abnormal["inputValue"] == '["a", "a"]'


def test_min_items_zero_no_abnormal():
    cases = generate_array_cases({"type": "array", "minItems": 0}, {"paramName": "tags", "opts": ALL_OPTS})
    abnormal = [c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("異常系")]
    assert len(abnormal) == 0
