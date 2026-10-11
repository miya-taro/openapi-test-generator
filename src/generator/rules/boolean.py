"""Exercise both declared boolean values, including false which is easy to omit accidentally."""
from jsonschema import Draft202012Validator


def generate_boolean_cases(schema: dict, ctx: dict) -> list[dict]:
    if not ctx["opts"]["includeNormal"]:
        return []
    validator = Draft202012Validator(schema)
    return [{
        "summary": f"{ctx['paramName']} {str(value).lower()}（正常）",
        "keyword": "boolean", "perspective": "正常系_boolean",
        "inputValue": str(value).lower(), "expectedStatus": ctx.get("successStatus"),
        "expectedResult": "指定した真偽値が正常に処理されること", "notes": "",
    } for value in (True, False) if validator.is_valid(value)]
