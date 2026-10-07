"""Conservative JSON Schema example synthesis for valid operation-level requests."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from itertools import islice

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .samples.format_samples import FORMAT_VALID_SAMPLES

try:
    import exrex  # type: ignore
except ImportError:  # pragma: no cover - fallback when the optional regex helper is absent
    exrex = None


class NoSchemaExample(ValueError):
    """Raised when a schema cannot be satisfied by a safe, deterministic sample."""


def find_schema_example(schema: dict) -> object:
    """Return a deterministic example accepted by the schema or raise ``NoSchemaExample``.

    The helper is deliberately conservative: it validates each candidate before returning it and
    declines impossible/unsupported constraints instead of producing a misleading happy-path case.
    """
    if not isinstance(schema, dict):
        raise NoSchemaExample("schema is not an object")

    request_schema = _request_schema(schema)
    try:
        validator = Draft202012Validator(request_schema, format_checker=FormatChecker())
    except SchemaError as error:
        raise NoSchemaExample("schema is invalid") from error

    variants = schema.get("_oneOfVariants")
    if isinstance(variants, list) and variants:
        for variant in variants:
            try:
                candidate = find_schema_example(variant)
            except NoSchemaExample:
                continue
            if validator.is_valid(candidate):
                return candidate

    for candidate in _candidate_values(request_schema):
        if validator.is_valid(candidate):
            return candidate

    raise NoSchemaExample("no valid deterministic sample found")


def _request_schema(schema: dict) -> dict:
    """Remove request-irrelevant readOnly properties before validating a request sample."""
    result = deepcopy(schema)
    properties = result.get("properties")
    if isinstance(properties, dict):
        readonly = {
            name for name, prop in properties.items()
            if isinstance(prop, dict) and prop.get("readOnly") is True
        }
        for name in readonly:
            properties.pop(name, None)
        if isinstance(result.get("required"), list):
            result["required"] = [name for name in result["required"] if name not in readonly]
        for name, prop in list(properties.items()):
            if isinstance(prop, dict):
                properties[name] = _request_schema(prop)
    items = result.get("items")
    if isinstance(items, dict):
        result["items"] = _request_schema(items)
    additional = result.get("additionalProperties")
    if isinstance(additional, dict):
        result["additionalProperties"] = _request_schema(additional)
    return result


def _candidate_values(schema: dict) -> list[object]:
    if "const" in schema:
        return [schema["const"]]
    enum = schema.get("enum")
    if isinstance(enum, list):
        return list(enum)

    candidates: list[object] = []
    for key in ("example", "default"):
        if key in schema:
            candidates.append(schema[key])

    type_ = schema.get("type")
    if isinstance(type_, list):
        types = [value for value in type_ if value != "null"]
        if not types:
            candidates.append(None)
        else:
            for non_null_type in types:
                candidates.extend(_candidates_for_type(schema, non_null_type))
        if "null" in type_:
            candidates.append(None)
    elif type_ is not None:
        candidates.extend(_candidates_for_type(schema, type_))
    elif "properties" in schema:
        candidates.extend(_candidates_for_type(schema, "object"))
    else:
        candidates.extend(("test", 1, True, None, {}, []))

    unique: list[object] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _candidates_for_type(schema: dict, type_: str) -> list[object]:
    if type_ == "string":
        return _string_candidates(schema)
    if type_ in {"integer", "number"}:
        return _number_candidates(schema, type_)
    if type_ == "boolean":
        return [True, False]
    if type_ == "array":
        return _array_candidates(schema)
    if type_ == "object":
        return _object_candidates(schema)
    if type_ == "null":
        return [None]
    return []


def _string_candidates(schema: dict) -> list[str]:
    candidates: list[str] = []
    fmt = schema.get("format")
    if fmt in FORMAT_VALID_SAMPLES:
        candidates.append(FORMAT_VALID_SAMPLES[fmt])
    if fmt == "email":
        candidates.extend(("a@b.co", "a@b.com", "ab@b.co", "test@example.com"))

    pattern = schema.get("pattern")
    if isinstance(pattern, str) and exrex is not None:
        try:
            candidates.extend(islice(exrex.generate(pattern), 100))
        except Exception:  # a malformed/unsupported regex is caught by final schema validation
            pass

    minimum = schema.get("minLength", 0)
    maximum = schema.get("maxLength")
    if isinstance(minimum, int) and minimum > 0:
        candidates.extend(("a" * minimum, "x" * minimum, "0" * minimum))
    candidates.extend(("test", "a", "x", "0", ""))
    if isinstance(maximum, int) and maximum >= 0:
        candidates.extend(("a" * maximum, "x" * maximum, "0" * maximum))

    return candidates


def _number_candidates(schema: dict, type_: str) -> list[int | float]:
    try:
        lower = Decimal(str(schema["minimum"])) if "minimum" in schema else None
        upper = Decimal(str(schema["maximum"])) if "maximum" in schema else None
        exclusive_lower = schema.get("exclusiveMinimum")
        exclusive_upper = schema.get("exclusiveMaximum")
        if isinstance(exclusive_lower, (int, float)) and not isinstance(exclusive_lower, bool):
            lower = max(lower, Decimal(str(exclusive_lower))) if lower is not None else Decimal(str(exclusive_lower))
        if isinstance(exclusive_upper, (int, float)) and not isinstance(exclusive_upper, bool):
            upper = min(upper, Decimal(str(exclusive_upper))) if upper is not None else Decimal(str(exclusive_upper))
        step = Decimal(str(schema.get("multipleOf", 1 if type_ == "integer" else "0.1")))
        increment = Decimal(1) if type_ == "integer" else min(step, Decimal("0.1"))
        base = lower if lower is not None else Decimal(0)
        if exclusive_lower is not None:
            base += increment
        if step > 0:
            base = (base / step).to_integral_value(rounding=ROUND_CEILING) * step
            if exclusive_lower is not None and lower is not None and base <= lower:
                base += step
        values = [base, base + step, Decimal(0), Decimal(1), Decimal(-1)]
        if upper is not None:
            values.extend((upper, upper - increment))
        candidates: list[int | float] = []
        for value in values:
            if type_ == "integer":
                if value == value.to_integral_value():
                    candidates.append(int(value))
            else:
                candidates.append(float(value))
        return candidates
    except (InvalidOperation, ValueError, TypeError):
        return [0, 1, -1] if type_ == "integer" else [0.0, 1.0, -1.0]


def _array_candidates(schema: dict) -> list[list[object]]:
    min_items = schema.get("minItems", 0)
    max_items = schema.get("maxItems")
    if not isinstance(min_items, int) or min_items < 0:
        return []
    count = max(min_items, 1)
    if max_items == 0:
        count = 0
    if isinstance(max_items, int) and count > max_items:
        return []
    if count > 100:
        return []
    item_schema = schema.get("items") or {}
    item_candidates = _candidate_values(item_schema) if isinstance(item_schema, dict) else []
    if not item_candidates:
        return []
    values: list[object] = []
    unique = schema.get("uniqueItems") is True
    for index in range(count):
        chosen = next((
            candidate for candidate in item_candidates
            if not unique or candidate not in values
        ), _NO_VALUE)
        if chosen is _NO_VALUE:
            chosen = _alternate_item(item_schema, index, values, item_candidates)
        if chosen is _NO_VALUE:
            return []
        values.append(chosen)
    return [values]


_NO_VALUE = object()


def _alternate_item(schema: dict, index: int, used: list[object], candidates: list[object]) -> object:
    for suffix in range(1, 101):
        type_ = schema.get("type", "string")
        if type_ == "integer":
            candidate = suffix
        elif type_ == "number":
            candidate = float(suffix)
        elif type_ == "boolean":
            candidate = bool(suffix % 2)
        else:
            base = next((value for value in candidates if isinstance(value, str)), "a")
            candidate = f"{base}{suffix}"
        if candidate in used:
            continue
        try:
            if Draft202012Validator(_request_schema(schema), format_checker=FormatChecker()).is_valid(candidate):
                return candidate
        except SchemaError:
            return _NO_VALUE
    return _NO_VALUE


def _object_candidates(schema: dict) -> list[dict]:
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    result: dict[str, object] = {}
    for name in required:
        property_schema = properties.get(name)
        if isinstance(property_schema, dict) and property_schema.get("readOnly") is True:
            continue
        if isinstance(property_schema, dict):
            try:
                result[name] = find_schema_example(property_schema)
            except NoSchemaExample:
                return []
        elif schema.get("additionalProperties") is False:
            return []
        elif isinstance(schema.get("additionalProperties"), dict):
            try:
                result[name] = find_schema_example(schema["additionalProperties"])
            except NoSchemaExample:
                return []
        else:
            result[name] = "test"

    min_properties = schema.get("minProperties", 0)
    additional = schema.get("additionalProperties", True)
    if isinstance(min_properties, int) and len(result) < min_properties:
        if additional is False:
            return []
        for index in range(min_properties - len(result)):
            name = f"__sample_{index + 1}__"
            if name in result:
                continue
            if isinstance(additional, dict):
                try:
                    result[name] = find_schema_example(additional)
                except NoSchemaExample:
                    return []
            else:
                result[name] = "test"
    return [result]
