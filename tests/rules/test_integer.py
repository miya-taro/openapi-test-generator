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
        {"type": "integer", "exclusiveMinimum": 10}, {"paramName": "n", "opts": ALL_OPTS}
    )
    abnormal = next(c for c in cases if "exclusiveMinimum境界値" in c["perspective"])
    normal = next(c for c in cases if "exclusiveMinimum超過値" in c["perspective"])
    assert abnormal["inputValue"] == "10"
    assert normal["inputValue"] == "11"


def test_exclusive_minimum_boolean_form_is_ignored_unnormalized():
    # parser.py を経由していない生スキーマ（bool形式）は正規化前提のため無視される
    cases = generate_integer_cases(
        {"type": "integer", "minimum": 10, "exclusiveMinimum": True}, {"paramName": "n", "opts": ALL_OPTS}
    )
    assert not any(c["keyword"] == "exclusiveMinimum" for c in cases)


def test_exclusive_maximum_value():
    cases = generate_integer_cases(
        {"type": "integer", "exclusiveMaximum": 100}, {"paramName": "n", "opts": ALL_OPTS}
    )
    abnormal = next(c for c in cases if "exclusiveMaximum境界値" in c["perspective"])
    normal = next(c for c in cases if "exclusiveMaximum未満値" in c["perspective"])
    assert abnormal["inputValue"] == "100"
    assert normal["inputValue"] == "99"


def test_exclusive_maximum_number_type_uses_decimal_step():
    cases = generate_integer_cases(
        {"type": "number", "exclusiveMaximum": 1.0}, {"paramName": "n", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if "exclusiveMaximum未満値" in c["perspective"])
    assert normal["inputValue"] == "0.9"


def test_multiple_of():
    cases = generate_integer_cases({"type": "integer", "multipleOf": 3}, {"paramName": "n", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "multipleOf" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "multipleOf" and c["perspective"].startswith("異常系"))
    assert normal["inputValue"] == "6"
    assert abnormal["inputValue"] == "4"


def test_multiple_of_unit_fraction_abnormal_value_is_not_actually_a_multiple():
    # multipleOf が 0.01 のような単位分数の場合、"+1" は正当な倍数(1.01)になってしまい
    # 自己矛盾したテストケースが生成されていた（0.01 の倍数を「異常系」として扱う）。
    cases = generate_integer_cases(
        {"type": "number", "multipleOf": 0.01}, {"paramName": "n", "opts": ABNORMAL_ONLY}
    )
    abnormal = next(c for c in cases if c["keyword"] == "multipleOf")
    value = float(abnormal["inputValue"])
    ratio = value / 0.01
    assert abs(ratio - round(ratio)) > 1e-6, f"{value} は 0.01 の倍数であってはならない"


def test_boundary_subtraction_does_not_leak_floating_point_noise():
    # 回帰テスト: 0.3 - 0.1 はIEEE754の丸め誤差で 0.19999999999999998 になるため、
    # 生成される inputValue にその誤差がそのまま出力されてはならない。
    cases = generate_integer_cases(
        {"type": "number", "minimum": 0.3}, {"paramName": "n", "opts": ABNORMAL_ONLY}
    )
    abnormal = next(c for c in cases if c["keyword"] == "minimum")
    assert abnormal["inputValue"] == "0.2"


def test_number_type_as_nullable_array_form_uses_decimal_step():
    # parser.py の nullable 正規化後は type が ["number", "null"] のような配列になる。
    # 配列形式でも number 型として扱われ、増減幅に 0.1 が使われる必要がある。
    cases = generate_integer_cases(
        {"type": ["number", "null"], "minimum": 1.5}, {"paramName": "n", "opts": ABNORMAL_ONLY}
    )
    abnormal = next(c for c in cases if c["keyword"] == "minimum")
    assert abnormal["inputValue"] == "1.4"
