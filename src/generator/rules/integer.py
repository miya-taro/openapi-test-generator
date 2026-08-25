"""integer / number 型のルール。"""
from __future__ import annotations


def generate_integer_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]
    is_number = "number" in _type_set(schema)
    step = 0.1 if is_number else 1

    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    # exclusiveMinimum/Maximum は parser.py で OAS バージョンによらず数値形式に正規化済みの前提
    # （bool は int のサブクラスのため isinstance チェックで明示的に除外する）
    ex_min_val = _as_number(schema.get("exclusiveMinimum"))
    ex_max_val = _as_number(schema.get("exclusiveMaximum"))

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
            # multiple_of が 0.01 のような単位分数の場合、"+1" は正当な倍数になり
            # うる（例: 0.01 + 1 = 1.01 は 0.01 の倍数）。比率 1.5 倍の値は
            # multiple_of がどんな値でも整数倍にならないため、確実に非倍数となる。
            non_multiple = multiple_of * 1.5 if is_number else multiple_of + 1
            cases.append({
                "summary": f"{ctx['paramName']} multipleOf 非倍数値（異常）",
                "keyword": "multipleOf",
                "perspective": "異常系_multipleOf非倍数",
                "inputValue": _num_str(non_multiple),
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


def _as_number(value: object) -> float | int | None:
    """bool を除く int/float のみを数値として受け付ける（bool は int のサブクラスのため）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _type_set(schema: dict) -> set[str]:
    """schema["type"] を集合として返す（nullable 正規化後の配列形式にも対応）。"""
    t = schema.get("type")
    if isinstance(t, list):
        return set(t)
    if isinstance(t, str):
        return {t}
    return set()
