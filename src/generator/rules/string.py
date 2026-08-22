"""string 型のルール（enum / maxLength / minLength / pattern / format）。"""
from __future__ import annotations
import re

from ...samples.format_samples import FORMAT_VALID_SAMPLES, FORMAT_INVALID_SAMPLES
from ... import logger as log

try:
    import exrex  # type: ignore
except ImportError:  # pragma: no cover - exrex 未導入環境向けフォールバック
    exrex = None


def generate_string_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    # enum
    enum = schema.get("enum")
    if enum:
        if opts["includeNormal"]:
            if opts.get("enumFullCoverage"):
                for val in enum:
                    cases.append({
                        "summary": f'{ctx["paramName"]} enum 値 "{val}"（正常）',
                        "keyword": "enum",
                        "perspective": "正常系_enum値",
                        "inputValue": str(val),
                        "expectedStatus": ctx.get("successStatus"),
                        "expectedResult": "正常に処理されること",
                        "notes": "",
                    })
            else:
                cases.append({
                    "summary": f"{ctx['paramName']} enum 代表値（正常）",
                    "keyword": "enum",
                    "perspective": "正常系_enum代表値",
                    "inputValue": str(enum[0]),
                    "expectedStatus": ctx.get("successStatus"),
                    "expectedResult": "正常に処理されること",
                    "notes": "",
                })

        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} enum 外の値（異常）",
                "keyword": "enum",
                "perspective": "異常系_enum外値",
                "inputValue": "__INVALID__",
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # maxLength
    max_length = schema.get("maxLength")
    if max_length is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大長（正常）",
                "keyword": "maxLength",
                "perspective": "正常系_最大長",
                "inputValue": "a" * max_length,
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })
        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大長+1（異常）",
                "keyword": "maxLength",
                "perspective": "異常系_最大長超過",
                "inputValue": "a" * (max_length + 1),
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # minLength
    min_length = schema.get("minLength")
    if min_length is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最小長（正常）",
                "keyword": "minLength",
                "perspective": "正常系_最小長",
                "inputValue": "a" * min_length,
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        # minLength = 0 の場合は異常系なし
        if min_length > 0 and opts["includeAbnormal"]:
            invalid_len = min_length - 1 if min_length > 1 else 0
            cases.append({
                "summary": f"{ctx['paramName']} 最小長-1（異常）",
                "keyword": "minLength",
                "perspective": "異常系_最小長未満",
                "inputValue": "（空文字）" if invalid_len == 0 else "a" * invalid_len,
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # pattern
    pattern = schema.get("pattern")
    if pattern:
        valid_value = _reverse_generate_pattern(pattern)

        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} パターン一致（正常）",
                "keyword": "pattern",
                "perspective": "正常系_patternマッチ",
                "inputValue": valid_value if valid_value is not None else "[手動入力]",
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "" if valid_value is not None else f"正規表現: {pattern}",
            })

        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} パターン不一致（異常）",
                "keyword": "pattern",
                "perspective": "異常系_patternミスマッチ",
                "inputValue": "__BAD_PATTERN__",
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # format
    fmt = schema.get("format")
    if fmt and fmt != "binary":
        valid_sample = FORMAT_VALID_SAMPLES.get(fmt)
        invalid_sample = FORMAT_INVALID_SAMPLES.get(fmt)

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

        if invalid_sample and opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} format:{fmt} 不適合値（異常）",
                "keyword": "format",
                "perspective": f"異常系_format_{fmt}",
                "inputValue": invalid_sample,
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "サーバが format をバリデートしない場合 200 の可能性あり",
            })

    return cases


def _reverse_generate_pattern(pattern: str) -> str | None:
    simple = _try_simple_pattern_generation(pattern)
    if simple is not None:
        return simple

    if exrex is None:
        log.info({"pattern": pattern}, "pattern 逆生成失敗（exrex未導入） → [手動入力]")
        return None

    try:
        result = next(exrex.generate(pattern), None)
        if result is not None and re.search(pattern, result):
            return result
        return None
    except Exception:
        log.info({"pattern": pattern}, "pattern 逆生成失敗 → [手動入力]")
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
