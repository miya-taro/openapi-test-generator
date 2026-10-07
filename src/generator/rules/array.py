"""array 型のルール（minItems / maxItems / uniqueItems）。"""
from __future__ import annotations
import json

from ...schema_example import NoSchemaExample, find_schema_example


def generate_array_cases(schema: dict, ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    item_schema = schema.get("items") or {}
    item_type = _infer_type(item_schema)
    sample_item = _get_sample_item(item_type, item_schema)

    # minItems
    min_items = schema.get("minItems")
    if min_items is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最小要素数（正常）",
                "keyword": "minItems",
                "perspective": "正常系_minItems",
                "inputValue": _build_array_value(sample_item, min_items),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"] and min_items > 0:
            cases.append({
                "summary": f"{ctx['paramName']} 最小要素数-1（異常）",
                "keyword": "minItems",
                "perspective": "異常系_minItems未満",
                "inputValue": _build_array_value(sample_item, min_items - 1),
                "expectedStatus": "4xx",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # maxItems
    max_items = schema.get("maxItems")
    if max_items is not None:
        if opts["includeNormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大要素数（正常）",
                "keyword": "maxItems",
                "perspective": "正常系_maxItems",
                "inputValue": _build_array_value(sample_item, max_items),
                "expectedStatus": ctx.get("successStatus"),
                "expectedResult": "正常に処理されること",
                "notes": "",
            })

        if opts["includeAbnormal"]:
            cases.append({
                "summary": f"{ctx['paramName']} 最大要素数+1（異常）",
                "keyword": "maxItems",
                "perspective": "異常系_maxItems超過",
                "inputValue": _build_array_value(sample_item, max_items + 1),
                "expectedStatus": "4xx",
                "expectedResult": "バリデーションエラーが返ること",
                "notes": "",
            })

    # uniqueItems
    if schema.get("uniqueItems") is True and opts["includeAbnormal"]:
        cases.append({
            "summary": f"{ctx['paramName']} 重複要素あり（異常）",
            "keyword": "uniqueItems",
            "perspective": "異常系_uniqueItems重複",
            "inputValue": f"[{sample_item}, {sample_item}]",
            "expectedStatus": "4xx",
            "expectedResult": "バリデーションエラーが返ること",
            "notes": "",
        })

    return cases


def _get_sample_item(item_type: str, item_schema: dict) -> str:
    """minItems/maxItems 境界値テスト用の要素1個分のJSONリテラル（文字列）を返す。

    要素が object 型の場合、単純に文字列プレースホルダ（"a"）を使うと構造的に不正な
    要素になり、境界値以外の理由（型不正）で失敗する誤ったテストケースになってしまう
    ため、items スキーマの required プロパティを埋めた最小限のオブジェクトを生成する。
    """
    try:
        return json.dumps(find_schema_example(item_schema), ensure_ascii=False, separators=(",", ":"))
    except NoSchemaExample:
        pass

    if item_type in ("integer", "number"):
        return "1"
    if item_type == "boolean":
        return "true"
    if item_type == "object":
        return json.dumps(_build_sample_object(item_schema), ensure_ascii=False)
    if item_type == "array":
        return "[]"
    return '"a"'


def _infer_type(schema: dict) -> str:
    """schema["type"]が無指定でも、propertiesがあればobject型として扱う。

    JSON Schemaではtypeの明示は必須ではなく、properties/requiredだけを書いた
    スキーマも正当（typeがobjectであることは暗黙的に分かる）。ここを見落として
    素朴に"string"にフォールバックすると、object型を期待する要素に文字列
    プレースホルダを埋めてしまい、境界値以外の理由（型不正）で失敗する
    誤ったテストケースになる。
    """
    t = schema.get("type")
    if t:
        return t
    if "properties" in schema:
        return "object"
    return "string"


def _build_sample_object(item_schema: dict) -> dict:
    properties = item_schema.get("properties") or {}
    required = item_schema.get("required") or list(properties.keys())
    return {name: _sample_scalar(properties.get(name) or {}) for name in required}


def _sample_scalar(prop_schema: dict):
    prop_type = _infer_type(prop_schema)
    if prop_type in ("integer", "number"):
        return 1
    if prop_type == "boolean":
        return True
    if prop_type == "array":
        return []
    if prop_type == "object":
        return _build_sample_object(prop_schema)
    return "a"


def _build_array_value(item: str, count: int) -> str:
    if count == 0:
        return "[]"
    return f"[{', '.join([item] * count)}]"
