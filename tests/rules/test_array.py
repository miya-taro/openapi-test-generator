import json

from src.generator.rules.array import generate_array_cases
from jsonschema import Draft202012Validator

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}


def test_min_items():
    cases = generate_array_cases(
        {"type": "array", "minItems": 2, "items": {"type": "string"}}, {"paramName": "tags", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("異常系"))
    normal_value = json.loads(normal["inputValue"])
    abnormal_value = json.loads(abnormal["inputValue"])
    item_validator = Draft202012Validator({"type": "string"})
    assert len(normal_value) == 2
    assert len(abnormal_value) == 1
    assert all(item_validator.is_valid(item) for item in normal_value + abnormal_value)


def test_max_items():
    cases = generate_array_cases(
        {"type": "array", "maxItems": 3, "items": {"type": "integer"}}, {"paramName": "ids", "opts": ALL_OPTS}
    )
    normal = next(c for c in cases if c["keyword"] == "maxItems" and c["perspective"].startswith("正常系"))
    abnormal = next(c for c in cases if c["keyword"] == "maxItems" and c["perspective"].startswith("異常系"))
    normal_value = json.loads(normal["inputValue"])
    abnormal_value = json.loads(abnormal["inputValue"])
    item_validator = Draft202012Validator({"type": "integer"})
    assert len(normal_value) == 3
    assert len(abnormal_value) == 4
    assert all(item_validator.is_valid(item) for item in normal_value + abnormal_value)


def test_unique_items():
    cases = generate_array_cases(
        {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        {"paramName": "tags", "opts": ALL_OPTS},
    )
    abnormal = next(c for c in cases if c["keyword"] == "uniqueItems")
    assert "異常系" in abnormal["perspective"]
    parsed = json.loads(abnormal["inputValue"])
    assert len(parsed) == 2
    assert parsed[0] == parsed[1]
    assert all(Draft202012Validator({"type": "string"}).is_valid(item) for item in parsed)


def test_min_items_zero_no_abnormal():
    cases = generate_array_cases({"type": "array", "minItems": 0}, {"paramName": "tags", "opts": ALL_OPTS})
    abnormal = [c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("異常系")]
    assert len(abnormal) == 0


def test_min_items_with_object_array_fills_required_properties():
    # 要素が object 型の場合、単純な文字列プレースホルダ("a")では構造的に不正な要素になり
    # minItems の境界とは無関係の理由（型不正）で失敗する誤ったテストケースになってしまう。
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "required": ["product_name", "quantity"],
            "properties": {
                "product_name": {"type": "string"},
                "quantity": {"type": "integer"},
                "note": {"type": "string"},
            },
        },
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    parsed = json.loads(normal["inputValue"])
    assert len(parsed) == 1
    assert Draft202012Validator(schema["items"]).is_valid(parsed[0])
    # required にない任意項目(note)は含めない
    assert "note" not in parsed[0]


def test_max_items_with_object_array_produces_valid_json_elements():
    import json

    schema = {
        "type": "array",
        "maxItems": 2,
        "items": {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    abnormal = next(c for c in cases if c["keyword"] == "maxItems" and c["perspective"].startswith("異常系"))
    parsed = json.loads(abnormal["inputValue"])
    assert len(parsed) == 3
    assert all(Draft202012Validator(schema["items"]).is_valid(item) for item in parsed)


def test_object_array_without_required_uses_a_valid_minimal_object():
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "object", "properties": {"x": {"type": "integer"}}},
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    parsed = json.loads(normal["inputValue"])
    assert parsed == [{}]
    assert Draft202012Validator(schema["items"]).is_valid(parsed[0])


def test_object_array_without_explicit_type_still_inferred_as_object():
    # items スキーマが "type": "object" を明示せず properties/required だけを書いている
    # 場合（JSON Schema上typeの明示は必須ではない）でも、素朴に"string"へフォールバック
    # せずobject型として扱えること。素朴にフォールバックすると要素が"a"という文字列に
    # なり、構造的に不正な要素になってしまう（本テストの回帰対象）。
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        },
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    parsed = json.loads(normal["inputValue"])
    assert len(parsed) == 1
    assert Draft202012Validator(schema["items"]).is_valid(parsed[0])


def test_object_array_nested_property_without_explicit_type_still_inferred_as_object():
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "required": ["inner"],
            "properties": {
                "inner": {"required": ["id"], "properties": {"id": {"type": "integer"}}},
            },
        },
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    parsed = json.loads(normal["inputValue"])
    assert len(parsed) == 1
    assert Draft202012Validator(schema["items"]).is_valid(parsed[0])


def test_object_array_nested_object_property_recurses():
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "required": ["inner"],
            "properties": {
                "inner": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {"id": {"type": "integer"}},
                }
            },
        },
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    parsed = json.loads(normal["inputValue"])
    assert len(parsed) == 1
    assert Draft202012Validator(schema["items"]).is_valid(parsed[0])
