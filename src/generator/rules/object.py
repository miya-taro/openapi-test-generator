"""object 型のルール（additionalProperties / 空 body）。"""
from __future__ import annotations

from .common import _get_invalid_value_for_type


def generate_object_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]
    additional_props = schema.get("additionalProperties")

    # additionalProperties: false — 未定義プロパティ追加（異常）
    if opts["includeAbnormal"] and additional_props is False:
        cases.append({
            "summary": f"{ctx['paramName']} 未定義プロパティ追加（異常）",
            "keyword": "additionalProperties",
            "perspective": "異常系_additionalProperties",
            "inputValue": '{ ...validBody, "__extra__": "value" }',
            "expectedStatus": "400",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "スキーマ外のキーを含む JSON",
        })

    # additionalProperties がスキーマ（型付きで追加プロパティを許可）の場合
    if isinstance(additional_props, dict):
        prop_type = additional_props.get("type")

        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 未定義プロパティ追加・型定義に適合（正常）",
                "keyword": "additionalProperties",
                "perspective": "正常系_additionalProperties型適合",
                "inputValue": f'{{ ...validBody, "__extra__": {_sample_value_for_type(prop_type)} }}',
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "additionalProperties のスキーマに適合する型の追加プロパティ",
            })

        if opts["includeAbnormal"] and prop_type:
            invalid_value = _get_invalid_value_for_type(prop_type)
            if invalid_value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 未定義プロパティ追加・型不適合（異常）",
                    "keyword": "additionalProperties",
                    "perspective": "異常系_additionalProperties型不適合",
                    "inputValue": f'{{ ...validBody, "__extra__": {invalid_value} }}',
                    "expectedStatus": "400",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "additionalProperties のスキーマに適合しない型の追加プロパティ",
                })
    elif additional_props is not False:
        # additionalProperties が未指定、または明示的に true の場合。
        # JSON Schema の既定は additionalProperties: true（任意の追加プロパティを許可）であり、
        # このケースが最も多い（多くのスキーマはそもそも additionalProperties を書かない）。
        # 「許可されているはずの追加プロパティを、実装が誤って拒否していないか」は
        # 上の2分岐（false/スキーマ指定）では一切カバーされず、これまで未検証だった。
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 未定義プロパティ追加・制限なし（正常）",
                "keyword": "additionalProperties",
                "perspective": "正常系_additionalProperties制限なし",
                "inputValue": '{ ...validBody, "__extra__": "value" }',
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "additionalProperties が未指定/true のためスキーマ外のキーがあっても許可されるはず",
            })

    # 空 body（required プロパティが 1 件以上ある場合のみ）
    if opts["includeAbnormal"]:
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


def _sample_value_for_type(type_: str | None) -> str:
    if type_ in ("integer", "number"):
        return "1"
    if type_ == "boolean":
        return "true"
    if type_ == "array":
        return "[]"
    if type_ == "object":
        return "{}"
    return '"value"'
