"""array 型のルール（minItems / maxItems / uniqueItems）。"""
from __future__ import annotations


def generate_array_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    item_type = (schema.get("items") or {}).get("type") or "string"
    sample_item = _get_sample_item(item_type)

    # minItems
    min_items = schema.get("minItems")
    if min_items is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最小要素数（正常）",
                "keyword": "minItems",
                "perspective": "正常系_minItems",
                "inputValue": _build_array_value(sample_item, min_items),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"] and min_items > 0:
            cases.append({
                "summary": f"{ctx['paramName']} 最小要素数-1（異常）",
                "keyword": "minItems",
                "perspective": "異常系_minItems未満",
                "inputValue": _build_array_value(sample_item, min_items - 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # maxItems
    max_items = schema.get("maxItems")
    if max_items is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大要素数（正常）",
                "keyword": "maxItems",
                "perspective": "正常系_maxItems",
                "inputValue": _build_array_value(sample_item, max_items),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大要素数+1（異常）",
                "keyword": "maxItems",
                "perspective": "異常系_maxItems超過",
                "inputValue": _build_array_value(sample_item, max_items + 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # uniqueItems
    if schema.get("uniqueItems") is True and opts["includeAbnormal"]:
        cases.append({
            "summary": f"{ctx['paramName']} 重複要素あり（異常）",
            "keyword": "uniqueItems",
            "perspective": "異常系_uniqueItems重複",
            "inputValue": f"[{sample_item}, {sample_item}]",
            "expectedStatus": "400",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "",
        })

    return cases


def _get_sample_item(item_type: str) -> str:
    if item_type in ("integer", "number"):
        return "1"
    if item_type == "boolean":
        return "true"
    return '"a"'


def _build_array_value(item: str, count: int) -> str:
    if count == 0:
        return "[]"
    return f"[{', '.join([item] * count)}]"
