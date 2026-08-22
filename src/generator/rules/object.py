"""object 型のルール（additionalProperties / 空 body）。"""
from __future__ import annotations


def generate_object_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []

    if not ctx["opts"]["includeAbnormal"]:
        return cases

    # additionalProperties: false — 未定義プロパティ追加（異常）
    if schema.get("additionalProperties") is False:
        cases.append({
            "summary": f"{ctx['paramName']} 未定義プロパティ追加（異常）",
            "keyword": "additionalProperties",
            "perspective": "異常系_additionalProperties",
            "inputValue": '{ ...validBody, "__extra__": "value" }',
            "expectedStatus": "400",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "スキーマ外のキーを含む JSON",
        })

    # 空 body（required プロパティが 1 件以上ある場合のみ）
    required = schema.get("required") or []
    if ctx.get("isRootBody") and len(required) > 0:
        cases.append({
            "summary": f"{ctx['paramName']} 空 body（異常）",
            "keyword": "required",
            "perspective": "異常系_空body",
            "inputValue": "{}",
            "expectedStatus": "400",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "required プロパティが存在するため空 body は不正",
        })

    return cases
