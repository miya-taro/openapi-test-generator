"""共通ルール（required, type）。全型・全 in に適用される。"""
from __future__ import annotations

import json
from jsonschema import Draft202012Validator, FormatChecker

from ...case_values import encode_json_value
from ...samples.format_samples import FORMAT_VALID_SAMPLES
from ...schema_contract import CONTRACT, validation_schema
from ...schema_example import find_schema_example, NoSchemaExample

# body フィールド（requestBody ルート・ネスト両方）向けの oneOf/anyOf バリアント用マーカー。
# runner/request_builder.py の _ONE_OF_VARIANT_MARKER_PREFIX と対応させている
# （末尾に schema["_oneOfVariants"] のインデックスを付与した文字列として使う）。
#
# body フィールドでこのマーカー方式を使う理由: バリアントごとに型が異なりうる
# （例: oneOf の一方が object、もう一方が string）ため、request_builder.py 側で
# 実行時にスキーマを見て正しい型として組み立てる必要がある。一方 path/query/header/
# cookie パラメータは常に文字列として送信されるため、こちらは生成時に直接
# バリアントの代表値を文字列化して埋め込む（マーカーは使わない）。
ONE_OF_VARIANT_MARKER_PREFIX = "__ONE_OF_VARIANT__"


def generate_common_cases(schema: dict, required: bool, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    # required: false — 省略可能パラメータ省略時の正常系
    if not required and not ctx.get("skipPresence") and opts["includeNormal"]:
        cases.append({
            "summary": f"{ctx['paramName']} 省略（正常）",
            "keyword": "optional",
            "perspective": "正常系_省略",
            "inputValue": "（省略）",
            "expectedStatus": ctx.get("successStatus"),
            "expectedResult": "正常に処理されること",
            "notes": "",
        })

    # required: true — 必須欠落（異常）
    if required and not ctx.get("skipPresence") and opts["includeAbnormal"]:
        is_path = ctx.get("paramIn") == "path"
        cases.append({
            "summary": f"{ctx['paramName']} 必須フィールド欠落（異常）",
            "keyword": "required",
            "perspective": "異常系_必須欠落",
            "inputValue": "（フィールドを省略）",
            "expectedStatus": "4xx",
            "expectedResult": (
                "ルーティングまたは入力エラーとして4xxが返ること"
                if is_path else "バリデーションエラーが返ること"
            ),
            "notes": "ルーティング失敗により 404 の可能性あり" if is_path else "",
        })

    # Required means presence, not non-empty. Only declared string constraints decide validity.
    if required and "string" in _type_set(schema) and schema.get("format") != "binary":
        empty_valid = Draft202012Validator(schema, format_checker=FormatChecker()).is_valid("")
        if opts["includeNormal" if empty_valid else "includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} キーあり・空値（{'正常' if empty_valid else '異常'}）",
                "keyword": "required",
                "perspective": "正常系_空値" if empty_valid else "異常系_空値",
                "inputValue": "（空文字）",
                "expectedStatus": ctx.get("successStatus") if empty_valid else "4xx",
                "expectedResult": "正常に処理されること" if empty_valid else "バリデーションエラーが返ること",
                "notes": "空文字の可否はminLength・pattern・enum・format等の定義に従う",
            })

    # type — 型不正（異常）
    if schema.get("type") and opts["includeAbnormal"]:
        schema_type = schema["type"]
        if isinstance(schema_type, list):
            non_null_types = [value for value in schema_type if value != "null"]
            schema_type = non_null_types[0] if len(non_null_types) == 1 else None
        invalid_value = _get_invalid_value_for_type(schema_type) if schema_type and schema_type != "string" else None
        if invalid_value is not None:
            is_path = ctx.get("paramIn") == "path"
            cases.append({
                "summary": f"{ctx['paramName']} 型不正値（異常）",
                "keyword": "type",
                "perspective": "異常系_型不正",
                "inputValue": invalid_value,
                "expectedStatus": "4xx",
                "expectedResult": "型エラーが返ること",
                "notes": "ルーティング失敗により 404 になる場合あり（実装依存）" if is_path else "",
            })

    # JSON body types must stay typed on the wire ("123" is a valid string).
    if ctx.get("jsonBody", ctx.get("paramIn") == "body") and opts["includeAbnormal"] and schema.get("type") and schema.get("format") != "binary":
        type_validator = Draft202012Validator({"type": schema["type"]})
        for label, value in (("integer", 123), ("fractional", 1.5), ("boolean", True),
                             ("array", []), ("object", {}), ("string", "abc")):
            if type_validator.is_valid(value):
                continue
            cases.append({
                "summary": f"{ctx['paramName']} {label}型の不正入力（異常）",
                "keyword": "type", "perspective": f"異常系_型不正_{label}",
                "inputValue": encode_json_value(value), "expectedStatus": "4xx",
                "expectedResult": "型エラーが返ること", "notes": "JSONの型を保持して送信",
            })

    # nullable — null値の扱い
    # OAS 3.0: `nullable: true`、OAS 3.1: `type` 配列に "null" を含める、の両方に対応。
    if schema.get("type"):
        type_ = schema["type"]
        is_nullable = schema.get("nullable") is True or schema.get("type") == "null" or (
            isinstance(type_, list) and "null" in type_
        )
        if is_nullable and opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} null許容（正常）",
                "keyword": "nullable",
                "perspective": "正常系_null許容",
                "inputValue": "null",
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })
        elif not is_nullable and opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} null不可（異常）",
                "keyword": "nullable",
                "perspective": "異常系_null不可",
                "inputValue": "null",
                "expectedStatus": "4xx",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "nullable が明示されていないため null は不正な値として扱う",
            })

    return cases


def generate_one_of_variant_cases(schema: dict, ctx: dict) -> list[dict]:
    """`--one-of-full-coverage` 指定時、oneOf/anyOf の代表バリアント以外の各バリアントに
    ついても「正常系」ケースを1件ずつ追加する。

    デフォルト動作（フラグ未指定）では何も生成しない。対象は parser.py の
    _reduce_one_of_any_of が oneOf/anyOf を残したスキーマ全て（requestBody ルート・
    ネストしたbodyフィールド・path/query/header/cookieパラメータのいずれでも、
    schema["_oneOfVariants"] があれば対象になる）。代表バリアント（インデックス0）は
    通常の型別ルールで既にカバーされているため、インデックス1以降のみを追加する。
    """
    opts = ctx["opts"]
    variants = schema.get("_oneOfVariants")
    if not variants or not opts.get("oneOfFullCoverage") or not opts["includeNormal"]:
        return []

    is_body = ctx.get("paramIn") == "body"
    cases = []
    for i in range(1, len(variants)):
        if CONTRACT in schema:
            try:
                candidate = find_schema_example(variants[i])
            except NoSchemaExample:
                continue
            if not Draft202012Validator(validation_schema(schema), format_checker=FormatChecker()).is_valid(candidate):
                continue
        if is_body:
            # バリアントごとに型が異なりうるため、実行時にスキーマを見て正しく
            # 組み立てられるよう request_builder.py 側で解決するマーカーにする。
            input_value = f"{ONE_OF_VARIANT_MARKER_PREFIX}{i}"
        else:
            # path/query/header/cookie は常に文字列として送信されるため、
            # ここで直接バリアントの代表値を文字列化して埋め込む。
            input_value = _stringify_example(candidate if CONTRACT in schema else _example_value(variants[i]))
        cases.append({
            "summary": f"{ctx['paramName']} oneOf/anyOf バリアント{i + 1}（正常）",
            "keyword": "oneOf",
            "perspective": f"正常系_oneOfバリアント{i + 1}",
            "inputValue": input_value,
            "expectedStatus": ctx.get("successStatus"),
            "expectedResult": "正常に処理されること",
            "notes": f"oneOf/anyOf の {i + 1} 番目のバリアントに適合するリクエスト",
        })
    return cases


def _example_value(schema: dict) -> object:
    """スキーマに適合する具体的な値を1つ合成する（oneOfバリアントの代表値算出用）。"""
    if not isinstance(schema, dict):
        return "test"
    if "default" in schema:
        return schema["default"]
    if "example" in schema:
        return schema["example"]
    enum = schema.get("enum")
    if enum:
        return enum[0]

    t = schema.get("type")
    t = t[0] if isinstance(t, list) else t

    if t in ("integer", "number"):
        minimum = schema.get("minimum")
        return minimum if minimum is not None else 1
    if t == "boolean":
        return True
    if t == "array":
        items = schema.get("items", {})
        return [_example_value(items)]
    if t == "object":
        props = schema.get("properties", {})
        required = schema.get("required", [])
        return {
            k: _example_value(props[k])
            for k in required
            if k in props and not props[k].get("readOnly")
        }

    fmt = schema.get("format", "")
    if fmt in FORMAT_VALID_SAMPLES:
        return FORMAT_VALID_SAMPLES[fmt]
    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len
    return "test"


def _stringify_example(value: object) -> str:
    """path/query/header/cookie パラメータ用に、Python値をinputValue文字列へ変換する。

    object/array は JSON 文字列として埋め込む（配列型クエリパラメータ等、他のルールでも
    同じ表現を使っている）。それ以外は JS の String(value) 相当
    （真偽値は小文字、整数値になる浮動小数点は小数点なし）。
    """
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _type_set(schema: dict) -> set[str]:
    """schema["type"] を集合として返す（OAS 3.1 の配列形式にも順不同対応）。"""
    t = schema.get("type")
    if isinstance(t, list):
        return set(t)
    if isinstance(t, str):
        return {t}
    return set()


def _get_invalid_value_for_type(type_: str | list[str]) -> str | None:
    # TS版は schema.type が配列（OAS 3.1 の複数型）の場合はアンラップせず、
    # switch の厳密比較がどの分岐にもマッチしない（＝ None）挙動をそのまま踏襲する。
    if type_ in ("integer", "number"):
        return '"abc"'
    if type_ == "boolean":
        return '"yes"'
    if type_ == "array":
        return '"not-an-array"'
    if type_ == "object":
        return '"not-an-object"'
    if type_ == "string":
        return "123"
    return None
