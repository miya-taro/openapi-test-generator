"""Numeric boundaries selected from valid intersections, never independent guesses."""

from decimal import Decimal
from jsonschema import Draft202012Validator, FormatChecker
from ...numeric_samples import numeric_candidates
from ...schema_contract import validation_schema


def generate_integer_cases(schema: dict, ctx: dict) -> list[dict]:
    schema = validation_schema(schema)
    # Raw OAS 3.0 booleans are normalized by the parser before reaching this rule.
    schema = {
        k: v
        for k, v in schema.items()
        if not (k in {"exclusiveMinimum", "exclusiveMaximum"} and isinstance(v, bool))
    }
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    cases = []
    type_ = schema.get("type")
    is_number = type_ == "number" or isinstance(type_, list) and "number" in type_
    step = Decimal("0.1") if is_number else Decimal(1)

    def add(keyword, label, preferred, normal):
        if not ctx["opts"]["includeNormal" if normal else "includeAbnormal"]:
            return
        relaxed = {k: v for k, v in schema.items() if k != keyword}
        other = Draft202012Validator(relaxed, format_checker=FormatChecker())
        pool = numeric_candidates(schema if normal else relaxed, preferred)
        if normal:
            pool += list(schema.get("enum", []))
            if "const" in schema:
                pool.append(schema["const"])
        pool = [
            v
            for v in pool
            if isinstance(v, (int, float))
            and not isinstance(v, bool)
            and validator.is_valid(v) == normal
            and (normal or other.is_valid(v))
        ]
        if not pool:
            return  # Coverage inventory records the ungenerated obligation.
        value = min(
            pool, key=lambda v: (abs(Decimal(str(v)) - Decimal(str(preferred[0]))), v)
        )
        cases.append(
            {
                "summary": f"{ctx['paramName']} {label}（{'正常' if normal else '異常'}）",
                "keyword": keyword,
                "perspective": ("正常系_" if normal else "異常系_") + label,
                "inputValue": _num_str(value),
                "expectedStatus": ctx.get("successStatus") if normal else "4xx",
                "expectedResult": "正常に処理されること"
                if normal
                else "バリデーションエラーが返ること",
                "notes": "他の数値制約も満たす値を選択",
            }
        )

    for key, positive, negative, direction in (
        ("minimum", "最小値", "最小値未満", -1),
        ("maximum", "最大値", "最大値超過", 1),
        ("exclusiveMinimum", "exclusiveMinimum超過値", "exclusiveMinimum境界値", -1),
        ("exclusiveMaximum", "exclusiveMaximum未満値", "exclusiveMaximum境界値", 1),
    ):
        if key not in schema:
            continue
        bound = Decimal(str(schema[key]))
        exclusive = key.startswith("exclusive")
        add(key, positive, [bound - direction * step if exclusive else bound], True)
        add(key, negative, [bound if exclusive else bound + direction * step], False)
    if "minimum" in schema and "maximum" in schema:
        mid = (Decimal(str(schema["minimum"])) + Decimal(str(schema["maximum"]))) / 2
        add("minimum+maximum", "中間値", [mid], True)
    if "multipleOf" in schema:
        multiple = Decimal(str(schema["multipleOf"]))
        add("multipleOf", "multipleOf倍数", [multiple * 2], True)
        add(
            "multipleOf",
            "multipleOf非倍数",
            [multiple * Decimal("1.5") if is_number else multiple + 1],
            False,
        )
    return cases


def _num_str(value):
    return (
        str(int(value))
        if isinstance(value, float) and value.is_integer()
        else str(value)
    )
