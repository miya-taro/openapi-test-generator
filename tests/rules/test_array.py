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
    assert parsed == [{"product_name": "a", "quantity": 1}]
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
    assert parsed == [{"ok": True}, {"ok": True}, {"ok": True}]


def test_object_array_without_required_falls_back_to_all_properties():
    import json

    schema = {
        "type": "array",
        "minItems": 1,
        "items": {"type": "object", "properties": {"x": {"type": "integer"}}},
    }
    cases = generate_array_cases(schema, {"paramName": "items", "opts": ALL_OPTS})
    normal = next(c for c in cases if c["keyword"] == "minItems" and c["perspective"].startswith("正常系"))
    assert json.loads(normal["inputValue"]) == [{"x": 1}]


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
    assert json.loads(normal["inputValue"]) == [{"name": "a"}]


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
    assert json.loads(normal["inputValue"]) == [{"inner": {"id": 1}}]


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
    assert json.loads(normal["inputValue"]) == [{"inner": {"id": 1}}]
