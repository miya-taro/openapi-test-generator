from src.generator.rules.boolean import generate_boolean_cases


def test_both_boolean_values_are_generated():
    cases = generate_boolean_cases({"type": "boolean"}, {"paramName": "enabled", "opts": {"includeNormal": True}, "successStatus": "2xx"})
    assert [case["inputValue"] for case in cases] == ["true", "false"]


def test_boolean_enum_and_disabled_normal_cases_are_respected():
    context = {"paramName": "enabled", "opts": {"includeNormal": True}}
    assert [case["inputValue"] for case in generate_boolean_cases({"type": "boolean", "enum": [False]}, context)] == ["false"]
    context["opts"]["includeNormal"] = False
    assert generate_boolean_cases({"type": "boolean"}, context) == []
