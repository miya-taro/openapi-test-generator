"""enum/const probes preserve JSON types and isolate the choice constraint."""

import json
from jsonschema import Draft202012Validator, FormatChecker
from ...case_values import encode_json_value
from ...schema_contract import validation_schema
from ...schema_example import _candidate_values
from ...numeric_samples import numeric_candidates


def generate_choice_cases(schema, ctx):
    schema = validation_schema(schema)
    cases = []
    for keyword in ("enum", "const"):
        if keyword not in schema:
            continue
        choices = schema["enum"] if keyword == "enum" else [schema["const"]]
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        relaxed = {k: v for k, v in schema.items() if k != keyword}
        other = Draft202012Validator(relaxed, format_checker=FormatChecker())
        positives = choices if ctx["opts"].get("enumFullCoverage") else choices[:1]

        def add(value, normal, keyword=keyword):
            if not ctx["opts"]["includeNormal" if normal else "includeAbnormal"]:
                return
            # String rules also serve serialized query/header parameters.
            if ctx.get("jsonBody", ctx.get("paramIn") == "body"):
                raw = encode_json_value(value)
            else:
                raw = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                )
            label = f"{keyword}値" if normal else f"{keyword}外値"
            cases.append(
                {
                    "summary": f"{ctx['paramName']} {label}",
                    "keyword": keyword,
                    "perspective": ("正常系_" if normal else "異常系_") + label,
                    "inputValue": raw,
                    "expectedStatus": ctx.get("successStatus") if normal else "4xx",
                    "expectedResult": "正常に処理されること"
                    if normal
                    else "バリデーションエラーが返ること",
                    "notes": "同じ型で他の制約を満たす値を使用",
                }
            )

        for value in positives:
            if validator.is_valid(value):
                add(value, True)
        candidates = ["__INVALID__", *_candidate_values(relaxed)]
        for value in choices:
            if isinstance(value, bool):
                candidates.append(not value)
            elif isinstance(value, (int, float)):
                candidates.extend(numeric_candidates(relaxed, [value - 1, value + 1]))
            elif isinstance(value, str):
                candidates.extend(["__INVALID__", value + "x", value[:-1]])
        # Avoid sentinel collisions; search is bounded and any gap remains visible.
        candidates.extend(f"__INVALID_{index}__" for index in range(len(choices) + 1))
        for value in candidates:
            if other.is_valid(value) and not validator.is_valid(value):
                add(value, False)
                break
    return cases
