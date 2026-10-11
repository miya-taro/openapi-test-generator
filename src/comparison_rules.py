"""Explicit cross-field numeric/date-time rules; never infer business constraints."""
from copy import deepcopy
from datetime import datetime, timedelta
import operator
import re
from decimal import Decimal

from jsonschema import Draft202012Validator, FormatChecker

KEY = "x-otg-comparison-rules"
OPERATORS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


def comparable(value, schema):
    if schema.get("format") == "date-time":
        parsed = datetime.fromisoformat(re.sub(r"\.\d+", "", value.upper()).replace("Z", "+00:00"))
        fraction = re.search(r"\.(\d+)", value)
        seconds = parsed.toordinal() * 86400 + parsed.hour * 3600 + parsed.minute * 60 + parsed.second
        seconds -= int(parsed.utcoffset().total_seconds())
        return seconds, Decimal("0." + fraction[1]) if fraction else Decimal(0)
    return value


def valid_value(value, schema):
    return Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(value)


def validate_rules(schema):
    rules = schema.get(KEY, [])
    if not isinstance(rules, list):
        raise ValueError(f"{KEY} は配列にしてください")
    if rules and schema.get("type", "object") != "object":
        raise ValueError("項目間比較のリクエストbodyはobjectにしてください")
    used = set()
    properties = schema.get("properties") or {}
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("operator"), str) or rule["operator"] not in OPERATORS:
            raise ValueError("項目間比較の条件は <、<=、>、>= から指定してください")
        fields = rule.get("fields")
        if not isinstance(fields, list) or len(fields) != 2 or not all(isinstance(n, str) and n in properties for n in fields):
            raise ValueError("項目間比較にはbodyの項目を2つ指定してください")
        if fields[0] == fields[1] or used.intersection(fields):
            raise ValueError("項目間比較の項目は、各条件で重複しないように指定してください")
        used.update(fields)
        schemas = [properties[n] for n in fields]
        if any(not isinstance(s, dict) or s.get("readOnly") for s in schemas):
            raise ValueError("項目間比較は送信可能なbody項目を指定してください")
        numeric = all(s.get("type") in ("number", "integer") for s in schemas)
        dates = all(s.get("type") == "string" and s.get("format") == "date-time" for s in schemas)
        if not (numeric or dates):
            raise ValueError("項目間比較は数値同士、またはdate-time同士で指定してください")
        if not all(k in rule and all(valid_value(rule[k], s) for s in schemas) for k in ("lower", "upper")):
            raise ValueError("項目間比較の小さい試験値・大きい試験値は、両方の項目schemaを満たす値にしてください")
        if comparable(rule["lower"], schemas[0]) >= comparable(rule["upper"], schemas[1]):
            raise ValueError("項目間比較の試験値は、小さい値 < 大きい値にしてください")


def matches(body, schema, rule):
    left, right = rule["fields"]
    props = schema["properties"]
    # Presence/type/format faults are checked separately; optional absent fields do not imply a rule.
    if any(name not in body or not valid_value(body[name], props[name]) for name in (left, right)):
        return True
    return OPERATORS[rule["operator"]](comparable(body[left], props[left]), comparable(body[right], props[right]))


def complete_comparisons(body, schema, target=None, ignore_index=None):
    """Keep the field under test intact and satisfy other declared value conditions."""
    props = schema.get("properties") or {}
    for index, rule in enumerate(schema.get(KEY) or []):
        if index == ignore_index or matches(body, schema, rule):
            continue
        left, right = rule["fields"]
        changes = [right] if target == left else [left] if target == right else [left, right]
        repaired = False
        for change in changes:
            anchor = body[left if change == right else right]
            candidates = [anchor, rule["lower"], rule["upper"]]
            if props[change].get("format") == "date-time":
                parsed = datetime.fromisoformat(anchor.upper().replace("Z", "+00:00"))
                for seconds in (-1, 1, -86400, 86400):
                    try:
                        candidates.append((parsed + timedelta(seconds=seconds)).isoformat())
                    except OverflowError:
                        pass
            else:
                step = props[change].get("multipleOf", 1)
                candidates += [anchor - step, anchor + step]
                candidates += [props[change][k] for k in ("minimum", "maximum") if k in props[change]]
            for candidate in candidates:
                if valid_value(candidate, props[change]) and matches({**body, change: candidate}, schema, rule):
                    body[change] = candidate
                    repaired = True
                    break
            if repaired:
                break
        if not repaired:
            raise ValueError(f"{left} {rule['operator']} {right} を満たす試験値を生成できません。項目の制約と試験値を確認してください")
    return body


def variant_values(rule, variant):
    low, high = rule["lower"], rule["upper"]
    return {"less": (low, high), "equal": (low, low), "greater": (high, low)}[variant]


def comparison_body(body, schema, index, variant):
    body = deepcopy(body)
    rule = schema[KEY][index]
    body.update(zip(rule["fields"], variant_values(rule, variant), strict=True))
    return complete_comparisons(body, schema, ignore_index=index)
