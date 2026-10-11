"""Explicit finite test obligations. Missing cases are not silently counted as covered."""

import json
from jsonschema import Draft202012Validator
from .case_values import coerce_value, JSON_VALUE_PREFIX


def case_value(case, schema):
    raw = case.get("inputValue", "")
    if (
        raw.startswith(("（", "__", "{ ...validBody,"))
        and raw != "（空文字）"
        and not raw.startswith(JSON_VALUE_PREFIX)
    ):
        raise ValueError("symbolic request")
    return (
        None
        if raw == "null"
        else coerce_value("" if raw == "（空文字）" else raw, schema)
    )


def obligations(schema, key, value, cases, location):
    """Yield (label, matching IDs, not-applicable reason) independently of rule dispatch."""

    def ids(predicate):
        matches = []
        for case in cases:
            try:
                if predicate(case):
                    matches.append(case["id"])
            except (ValueError, TypeError):
                pass
        return matches

    def normal(case):
        return case.get("perspective", "").startswith("正常")

    if key == "type" and location == "body":
        validator = Draft202012Validator({"type": value})
        for label, sample in (
            ("integer", 123),
            ("fractional", 1.5),
            ("boolean", True),
            ("string", "abc"),
            ("array", []),
            ("object", {}),
        ):
            if validator.is_valid(sample):
                continue

            def typed(c, sample=sample):
                actual = case_value(c, schema)
                same = type(actual) is type(sample)
                if type(sample) is float:
                    same = same and not actual.is_integer()
                return not normal(c) and same

            yield f"不正型:{label}", ids(typed), ""
    elif key in {"enum", "const"}:
        choices = value if key == "enum" else [value]
        for choice in choices:
            # JSON Schema equality distinguishes booleans from numbers.
            matcher = Draft202012Validator({"const": choice})
            yield (
                f"正常値:{json.dumps(choice, ensure_ascii=False)}",
                ids(
                    lambda c, matcher=matcher: (
                        normal(c) and matcher.is_valid(case_value(c, schema))
                    )
                ),
                "",
            )
        reason = ""
        if schema.get("type") == "boolean" and all(
            any(type(v) is bool and v == b for v in choices) for b in (True, False)
        ):
            reason = "booleanの全値が許可されるため、同型の範囲外値は存在しません"
        other = Draft202012Validator({k: v for k, v in schema.items() if k != key})
        yield (
            "同型の範囲外値",
            ids(lambda c: not normal(c) and other.is_valid(case_value(c, schema))),
            reason,
        )
    elif key in {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "additionalProperties",
        "nullable",
    }:
        for positive, label in ((True, "正常側"), (False, "異常側")):
            reason = ""
            if (
                not positive
                and key in {"minLength", "minItems", "minProperties"}
                and value == 0
            ):
                reason = "長さ・件数は負にならないため、0未満の値は存在しません"
            if not positive and key == "multipleOf" and schema.get("type") == "integer":
                from fractions import Fraction

                if Fraction(str(value)).numerator == 1:
                    reason = "全整数が倍数に該当するため、整数型の非倍数は存在しません"
            if key == "additionalProperties" and value is True and not positive:
                reason = "追加項目は許可されています"
            if key == "additionalProperties" and value is False and positive:
                reason = "追加項目を持つ正常ケースは仕様上存在しません"
            if key == "uniqueItems" and value is False:
                reason = "重複禁止の制約はありません"
            if key == "nullable" and bool(value) != positive:
                reason = "nullの正常・異常の一方のみが仕様に該当します"
            yield label, ids(lambda c, positive=positive: normal(c) == positive), reason
