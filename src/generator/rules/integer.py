"""integer / number 型のルール。"""
from __future__ import annotations


def generate_integer_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]
    is_number = schema.get("type") == "number"
    step = 0.1 if is_number else 1

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    ex_min_val = schema.get("_exclusiveMinimumValue")
    ex_max_val = schema.get("_exclusiveMaximumValue")

    # minimum
    if minimum is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最小値（正常）",
                "keyword": "minimum",
                "perspective": "正常系_最小値",
                "inputValue": _num_str(minimum),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最小値未満（異常）",
                "keyword": "minimum",
                "perspective": "異常系_最小値未満",
                "inputValue": _num_str(minimum - step if is_number else minimum - 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "小数点以下を考慮" if is_number else "",
            })

    # maximum
    if maximum is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大値（正常）",
                "keyword": "maximum",
                "perspective": "正常系_最大値",
                "inputValue": _num_str(maximum),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大値超過（異常）",
                "keyword": "maximum",
                "perspective": "異常系_最大値超過",
                "inputValue": _num_str(maximum + step if is_number else maximum + 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # 中間値（minimum + maximum の両方がある場合）
    if minimum is not None and maximum is not None and opts["includeNormal"]:
        mid = (minimum + maximum) // 2
        cases.append({
            "summary": f"{ctx['paramName']} 中間値（正常）",
            "keyword": "minimum+maximum",
            "perspective": "正常系_中間値",
            "inputValue": _num_str(mid),
            "expectedStatus": ctx.get("successStatus"),
            "expectedResult": "正常に処理されること",
            "notes": "",
        })

    # exclusiveMinimum
    if ex_min_val is not None:
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} exclusiveMinimum 境界値そのもの（異常）",
                "keyword": "exclusiveMinimum",
                "perspective": "異常系_exclusiveMinimum境界値",
                "inputValue": _num_str(ex_min_val),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} exclusiveMinimum 境界値+1（正常）",
                "keyword": "exclusiveMinimum",
                "perspective": "正常系_exclusiveMinimum超過値",
                "inputValue": _num_str(ex_min_val + step if is_number else ex_min_val + 1),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

    # exclusiveMaximum
    if ex_max_val is not None:
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} exclusiveMaximum 境界値そのもの（異常）",
                "keyword": "exclusiveMaximum",
                "perspective": "異常系_exclusiveMaximum境界値",
                "inputValue": _num_str(ex_max_val),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} exclusiveMaximum 境界値-1（正常）",
                "keyword": "exclusiveMaximum",
                "perspective": "正常系_exclusiveMaximum未満値",
                "inputValue": _num_str(ex_max_val - step if is_number else ex_max_val - 1),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

    # multipleOf
    multiple_of = schema.get("multipleOf")
    if multiple_of is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} multipleOf 倍数値（正常）",
                "keyword": "multipleOf",
                "perspective": "正常系_multipleOf倍数",
                "inputValue": _num_str(multiple_of * 2),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} multipleOf 非倍数値（異常）",
                "keyword": "multipleOf",
                "perspective": "異常系_multipleOf非倍数",
                "inputValue": _num_str(multiple_of + 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    return cases


def _num_str(value: float) -> str:
    """JS の String(number) 相当（整数値は小数点なしで出力）。"""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
