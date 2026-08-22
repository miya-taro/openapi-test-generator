"""共通ルール（required, type）。全型・全 in に適用される。"""
from __future__ import annotations


def generate_common_cases(schema: dict, required: bool, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    # required: false — 省略可能パラメータ省略時の正常系
    if not required and opts["includeNormal"]:
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
    if required and opts["includeAbnormal"]:
        is_path = ctx.get("paramIn") == "path"
        cases.append({
            "summary": f"{ctx['paramName']} 必須フィールド欠落（異常）",
            "keyword": "required",
            "perspective": "異常系_必須欠落",
            "inputValue": "（フィールドを省略）",
            "expectedStatus": "404" if is_path else "400",
            "expectedResult": (
                "ルーティング失敗によりリソースが見つからないこと"
                if is_path else "バリデーションエラーが返ること"
            ),
            "notes": "ルーティング失敗により 404 の可能性あり" if is_path else "",
        })

    # required かつ string → キーあり・空値（異常）
    # minLength >= 1 の場合は string.py 側で最小長-1 として "" を生成するが、
    # それは境界値テストであり「空値」の観点とは別なので両立させる
    if required and opts["includeAbnormal"]:
        t = schema.get("type")
        t = t[0] if isinstance(t, list) else t
        if t == "string":
            cases.append({
                "summary": f"{ctx['paramName']} キーあり・空値（異常）",
                "keyword": "required",
                "perspective": "異常系_空値",
                "inputValue": "（空文字）",
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "キーは存在するが値が空文字",
            })

    # type — 型不正（異常）
    if schema.get("type") and opts["includeAbnormal"]:
        invalid_value = _get_invalid_value_for_type(schema["type"])
        if invalid_value is not None:
            is_path = ctx.get("paramIn") == "path"
            cases.append({
                "summary": f"{ctx['paramName']} 型不正値（異常）",
                "keyword": "type",
                "perspective": "異常系_型不正",
                "inputValue": invalid_value,
                "expectedStatus": "400",
                "expectedResult": "型エラーが返ること",
                "notes": "ルーティング失敗により 404 になる場合あり（実装依存）" if is_path else "",
            })

    # nullable — null値の扱い
    # OAS 3.0: `nullable: true`、OAS 3.1: `type` 配列に "null" を含める、の両方に対応。
    if schema.get("type"):
        type_ = schema["type"]
        is_nullable = schema.get("nullable") is True or (
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
                "expectedStatus": "400",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "nullable が明示されていないため null は不正な値として扱う",
            })

    return cases


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
    return None
