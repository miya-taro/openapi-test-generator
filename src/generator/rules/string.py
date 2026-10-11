"""string 型のルール（enum / maxLength / minLength / pattern / format）。"""
from __future__ import annotations
from itertools import islice
import re

from .choices import generate_choice_cases
from ...samples.format_samples import FORMAT_VALID_SAMPLES, FORMAT_INVALID_SAMPLES
from ... import logger as log

try:
    import exrex  # type: ignore
except ImportError:  # pragma: no cover - exrex 未導入環境向けフォールバック
    exrex = None


def generate_string_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    if ctx.get("includeChoices", True):
        cases.extend(generate_choice_cases(schema, ctx))

    # maxLength
    max_length = schema.get("maxLength")
    if max_length is not None:
        if opts["includeNormal"]:
            value = _string_value_at_length(schema, max_length)
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最大長（正常）",
                    "keyword": "maxLength",
                    "perspective": "正常系_最大長",
                    "inputValue": value,
                    "expectedStatus": ctx.get("successStatus"),
                    "expectedResult": "正常に処理されること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "maxLength": max_length, "format": schema.get("format")},
                    "format/pattern と maxLength を同時に満たす値を生成できないため、最大長の正常ケースを省略",
                )
        if opts["includeAbnormal"]:
            value = _string_value_for_length(schema, max_length + 1, ignore_length="maxLength")
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最大長+1（異常）",
                    "keyword": "maxLength",
                    "perspective": "異常系_最大長超過",
                    "inputValue": value,
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "maxLength": max_length, "format": schema.get("format")},
                    "maxLength 以外の制約を満たす超過値を生成できないため、異常ケースを省略",
                )

    # minLength
    min_length = schema.get("minLength")
    if min_length is not None:
        if opts["includeNormal"]:
            value = _string_value_at_length(schema, min_length)
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最小長（正常）",
                    "keyword": "minLength",
                    "perspective": "正常系_最小長",
                    "inputValue": value,
                    "expectedStatus": ctx.get("successStatus"),
                    "expectedResult": "正常に処理されること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "minLength": min_length, "format": schema.get("format")},
                    "format/pattern と minLength を同時に満たす値を生成できないため、最小長の正常ケースを省略",
                )

        # minLength = 0 の場合は異常系なし
        if min_length > 0 and opts["includeAbnormal"]:
            invalid_len = min_length - 1 if min_length > 1 else 0
            value = _string_value_for_length(schema, invalid_len, ignore_length="minLength")
            if value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} 最小長-1（異常）",
                    "keyword": "minLength",
                    "perspective": "異常系_最小長未満",
                    "inputValue": "（空文字）" if value == "" else value,
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "minLength": min_length, "format": schema.get("format")},
                    "minLength 以外の制約を満たす不足値を生成できないため、異常ケースを省略",
                )

    # pattern
    pattern = schema.get("pattern")
    if pattern:
        valid_value = _valid_pattern_sample(schema, pattern)

        if opts["includeNormal"]:
            if valid_value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} パターン一致（正常）",
                    "keyword": "pattern",
                    "perspective": "正常系_patternマッチ",
                    "inputValue": valid_value,
                    "expectedStatus": ctx.get("successStatus"),
                    "expectedResult": "正常に処理されること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "pattern": pattern},
                    "pattern と他の制約を満たす正常値を生成できないため、pattern 正常ケースを省略",
                )

        if opts["includeAbnormal"]:
            invalid_value = _invalid_pattern_sample(schema, pattern)
            if invalid_value is not None:
                cases.append({
                    "summary": f"{ctx['paramName']} パターン不一致（異常）",
                    "keyword": "pattern",
                    "perspective": "異常系_patternミスマッチ",
                    "inputValue": invalid_value,
                    "expectedStatus": "4xx",
                    "expectedResult": "バリデーションエラーが返ること",
                    "notes": "",
                })
            else:
                log.warn(
                    {"paramName": ctx["paramName"], "pattern": pattern},
                    "pattern 以外の制約を満たす不一致値を生成できないため、pattern 異常ケースを省略",
                )

    # format
    fmt = schema.get("format")
    if fmt and fmt != "binary":
        valid_sample = _valid_format_sample(schema, fmt)
        invalid_sample = _invalid_format_sample(schema, fmt)

        if valid_sample and opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} format:{fmt} 適合値（正常）",
                "keyword": "format",
                "perspective": f"正常系_format_{fmt}",
                "inputValue": valid_sample,
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if invalid_sample is not None and opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} format:{fmt} 不適合値（異常）",
                "keyword": "format",
                "perspective": f"異常系_format_{fmt}",
                "inputValue": invalid_sample,
                "expectedStatus": "4xx",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "サーバが format をバリデートしない場合 200 の可能性あり",
            })

    return cases


def _string_value_at_length(schema: dict, length: int) -> str | None:
    """Create a boundary string without breaking another declared constraint."""
    return _string_value_for_length(schema, length)


def _string_value_for_length(
    schema: dict, length: int, ignore_length: str | None = None,
) -> str | None:
    """Create a string of one length while honoring every non-targeted constraint."""
    if "const" in schema:
        candidates = [schema["const"]]
    elif isinstance(schema.get("enum"), list):
        candidates = schema["enum"]
    else:
        fmt = schema.get("format")
        pattern = schema.get("pattern")
        if fmt == "email":
            value = _email_sample_at_length(length)
        elif fmt:
            value = FORMAT_VALID_SAMPLES.get(fmt)
        elif pattern:
            value = _pattern_sample_at_length(pattern, length)
        else:
            value = "a" * length
        candidates = [value]

    pattern = schema.get("pattern")
    for value in candidates:
        if not isinstance(value, str) or len(value) != length:
            continue
        if not _satisfies_other_string_constraints(schema, value, ignore_length):
            continue
        if pattern and not _matches_pattern(pattern, value):
            continue
        return value
    return None


def _valid_format_sample(schema: dict, fmt: str) -> str | None:
    """Return a known format sample only when it also satisfies its length/pattern rules."""
    if "const" in schema or isinstance(schema.get("enum"), list):
        candidates = [schema["const"]] if "const" in schema else schema["enum"]
        return next((
            value for value in candidates
            if isinstance(value, str) and _known_format_accepts(fmt, value)
            and _satisfies_other_string_constraints(schema, value)
        ), None)

    min_length = schema.get("minLength", 0)
    max_length = schema.get("maxLength")
    sample = FORMAT_VALID_SAMPLES.get(fmt)

    if fmt == "email":
        target_length = max(len(sample or ""), min_length)
        if max_length is not None:
            target_length = min(target_length, max_length)
        value = _email_sample_at_length(target_length)
    elif sample is not None:
        value = sample
    else:
        value = None

    if value is None or not _satisfies_other_string_constraints(schema, value):
        return None
    pattern = schema.get("pattern")
    if pattern and not _matches_pattern(pattern, value):
        return None
    return value


def _invalid_format_sample(schema: dict, fmt: str) -> str | None:
    """Return an invalid format sample that still passes the other declared constraints."""
    sample = FORMAT_INVALID_SAMPLES.get(fmt)
    if sample is None:
        return None
    candidates = [sample]
    if fmt == "email":
        candidates.extend(["a@b", "@example.com", "a@.com"])
    pattern = schema.get("pattern")
    for value in candidates:
        if not _satisfies_other_string_constraints(schema, value, ignore_format=True):
            continue
        if _known_format_accepts(fmt, value):
            continue
        if pattern and not _matches_pattern(pattern, value):
            continue
        return value
    return None


def _valid_pattern_sample(schema: dict, pattern: str) -> str | None:
    """Generate a pattern match that also respects the other known string constraints."""
    fmt = schema.get("format")
    enum = schema.get("enum")
    if "const" in schema:
        candidates = [schema["const"]]
    elif isinstance(enum, list):
        candidates = enum
    elif fmt in FORMAT_VALID_SAMPLES:
        candidates = _format_candidates(schema, fmt)
    else:
        candidates = [_reverse_generate_pattern(pattern)]
        min_length = schema.get("minLength", 0)
        max_length = schema.get("maxLength")
        for target in dict.fromkeys((min_length, max_length)):
            if isinstance(target, int) and target >= 0:
                candidates.append(_pattern_sample_at_length(pattern, target))

    for candidate in candidates:
        if not isinstance(candidate, str) or not _satisfies_other_string_constraints(schema, candidate):
            continue
        if _matches_pattern(pattern, candidate):
            return candidate
        if not _is_valid_regex(pattern):
            return None
    return None


def _invalid_pattern_sample(schema: dict, pattern: str) -> str | None:
    """Find a pattern mismatch that remains valid for enum, format, and length constraints."""
    fmt = schema.get("format")
    enum = schema.get("enum")
    if "const" in schema:
        candidates = [schema["const"]]
    elif isinstance(enum, list):
        candidates = enum
    elif fmt in FORMAT_VALID_SAMPLES:
        candidates = _format_candidates(schema, fmt)
    else:
        candidates = ["__BAD_PATTERN__", "!", "x", "0", "a", " ", ""]
        min_length = schema.get("minLength", 0)
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and min_length > 0:
            candidates.extend(char * min_length for char in "!x0a ")
        if isinstance(max_length, int) and max_length >= 0:
            candidates.extend(char * max_length for char in "!x0a ")

    for candidate in candidates:
        if not isinstance(candidate, str) or not _satisfies_other_string_constraints(schema, candidate):
            continue
        if not _is_valid_regex(pattern):
            return None
        if not _matches_pattern(pattern, candidate):
            return candidate
    return None


def _format_candidates(schema: dict, fmt: str) -> list[str]:
    sample = FORMAT_VALID_SAMPLES.get(fmt)
    if fmt != "email" or sample is None:
        return [sample] if sample is not None else []

    min_length = schema.get("minLength", 0)
    max_length = schema.get("maxLength")
    target_lengths = [len(sample)]
    if isinstance(min_length, int):
        target_lengths.append(min_length)
    if isinstance(max_length, int) and max_length <= 254:
        target_lengths.append(max_length)
    if isinstance(min_length, int) and isinstance(max_length, int) and min_length <= max_length:
        target_lengths.append(min(max(len(sample), min_length), max_length))
    values = [sample]
    values.extend(
        value for length in dict.fromkeys(target_lengths)
        if isinstance(length, int) and (value := _email_sample_at_length(length)) is not None
    )
    return list(dict.fromkeys(values))


def _within_string_length(schema: dict, value: str, ignore_length: str | None = None) -> bool:
    min_length = schema.get("minLength", 0)
    max_length = schema.get("maxLength")
    if ignore_length != "minLength" and len(value) < min_length:
        return False
    if ignore_length != "maxLength" and max_length is not None and len(value) > max_length:
        return False
    return True


def _satisfies_other_string_constraints(
    schema: dict, value: str, ignore_length: str | None = None, ignore_format: bool = False,
) -> bool:
    if not _within_string_length(schema, value, ignore_length):
        return False
    if "const" in schema and value != schema["const"]:
        return False
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    fmt = schema.get("format")
    if not ignore_format and not _known_format_accepts(fmt, value):
        return False
    return True


def _matches_pattern(pattern: str, value: str) -> bool:
    try:
        return re.search(pattern, value) is not None
    except re.error:
        return False


def _is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def _known_format_accepts(fmt: str | None, value: str) -> bool:
    if fmt == "email":
        local, separator, domain = value.partition("@")
        labels = domain.split(".")
        return bool(
            separator and local and len(local) <= 64 and len(value) <= 254
            and len(domain) <= 253 and len(labels) >= 2
            and all(1 <= len(label) <= 63 for label in labels)
            and len(labels[-1]) >= 2
            and re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
            and all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label) for label in labels)
        )
    sample = FORMAT_VALID_SAMPLES.get(fmt or "")
    return sample is None or value == sample


def _email_sample_at_length(length: int) -> str | None:
    """Make a syntactically valid ASCII email at a requested length (6..254)."""
    if length < 6 or length > 254:
        return None

    # Keep the local part within its 64 character limit and leave a multi-label domain.
    local_length = min(64, length - 5)
    domain_length = length - local_length - 1
    if domain_length < 4 or domain_length > 253:
        return None

    # Split the domain into labels of at most 63 characters and a two-character TLD.
    label_count = max(2, (domain_length + 63) // 64)
    label_chars = domain_length - (label_count - 1)
    if label_chars < label_count or label_chars > label_count * 63:
        return None
    lengths: list[int] = []
    remainder = label_chars
    for index in range(label_count):
        if index == label_count - 1:
            current = remainder
        else:
            remaining_labels = label_count - index - 1
            reserved = 2 + max(0, remaining_labels - 1)
            current = min(63, remainder - reserved)
        lengths.append(current)
        remainder -= current
    if remainder != 0 or lengths[-1] < 2:
        return None

    labels = [chr(ord("b") + i) * label_size for i, label_size in enumerate(lengths)]
    return "a" * local_length + "@" + ".".join(labels)


def _pattern_sample_at_length(pattern: str, length: int) -> str | None:
    """Find a bounded regex example with exactly the requested size."""
    simple = _try_simple_pattern_generation(pattern)
    if simple is not None and len(simple) == length:
        return simple
    if exrex is None:
        return None
    try:
        for candidate in islice(exrex.generate(pattern), 1000):
            if len(candidate) == length and re.search(pattern, candidate):
                return candidate
            if len(candidate) < length:
                pad_size = length - len(candidate)
                for char in dict.fromkeys(candidate + "a1_"):
                    padded = candidate + char * pad_size
                    if re.search(pattern, padded):
                        return padded
    except Exception:
        return None
    return None


def _reverse_generate_pattern(pattern: str) -> str | None:
    simple = _try_simple_pattern_generation(pattern)
    if simple is not None:
        return simple

    if exrex is None:
        log.info({"pattern": pattern}, "pattern 逆生成失敗（exrex未導入）")
        return None

    try:
        result = next(exrex.generate(pattern), None)
        if result is not None and re.search(pattern, result):
            return result
        return None
    except Exception:
        log.info({"pattern": pattern}, "pattern 逆生成失敗")
        return None


def _try_simple_pattern_generation(pattern: str) -> str | None:
    # ^[0-9]{N}$ 形式
    m = re.match(r"^\^?\[0-9\]\{(\d+)\}\$?$", pattern)
    if m:
        return "1" * int(m.group(1))

    # ^[a-zA-Z]{N}$ 形式
    m = re.match(r"^\^?\[a-zA-Z\]\{(\d+)\}\$?$", pattern)
    if m:
        return "a" * int(m.group(1))

    # ^[a-z0-9]{N,M}$ 形式
    m = re.match(r"^\^?\[a-z0-9\]\{(\d+),(\d+)\}\$?$", pattern)
    if m:
        return "a" * int(m.group(1))

    return None
