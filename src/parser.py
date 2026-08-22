"""OpenAPI 3.x のパース。

TypeScript版は `@apidevtools/swagger-parser` の `dereference()` を使用していたが、
このプロジェクトで使われる `$ref` は `#/components/...` 形式の内部参照のみのため、
軽量な自前実装で置き換える。
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from . import logger as log


class OpenAPIParseError(Exception):
    pass


def parse_openapi(input_path: str) -> dict:
    path = Path(input_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise OpenAPIParseError(f"openapi.json の解析に失敗しました: {e}") from e

    version = raw.get("openapi", "") if isinstance(raw, dict) else ""
    if not version.startswith("3."):
        raise OpenAPIParseError(
            f"OpenAPI 3.x のみ対応しています（検出バージョン: {version or '不明'}）"
        )

    api = _resolve_refs(raw, raw, ())
    _walk_schemas(api, _normalize_schema, set())

    log.info({"version": version}, "OpenAPI パース完了")
    return api


def _resolve_refs(node: Any, root: dict, stack: tuple[str, ...]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in stack:
                # 循環参照: これ以上展開せず空スキーマとして扱う
                return {}
            target = _lookup_ref(ref, root)
            return _resolve_refs(target, root, stack + (ref,))
        return {k: _resolve_refs(v, root, stack) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_refs(v, root, stack) for v in node]
    return node


def _lookup_ref(ref: str, root: dict) -> Any:
    if not ref.startswith("#/"):
        raise OpenAPIParseError(f"$ref の解決に失敗しました（外部参照は未対応）: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise OpenAPIParseError(f"$ref を解決できませんでした: {ref}")
        node = node[part]
    return node


def _normalize_schema(schema: dict) -> None:
    """スキーマ1件分の正規化（exclusiveMinimum/Maximum の数値化 + allOf/oneOf/anyOf の展開）を行う。

    正規化後のスキーマは標準の JSON Schema (2020-12) として妥当な形になる
    （$ref 済み・allOf/oneOf/anyOf 展開済み・exclusiveMinimum/Maximum は常に数値）。
    これにより、生成ロジックだけでなく `jsonschema` 等の汎用バリデータにも
    そのまま渡せる（ランナー側のレスポンスボディ検証で利用）。
    """
    _merge_all_of(schema)
    _reduce_one_of_any_of(schema)
    _normalize_exclusive_bound(schema, "minimum", "exclusiveMinimum")
    _normalize_exclusive_bound(schema, "maximum", "exclusiveMaximum")


def _normalize_exclusive_bound(schema: dict, bound_key: str, exclusive_key: str) -> None:
    """OAS 3.0 形式（`exclusiveMinimum: true` + `minimum: N`）を
    OAS 3.1 / JSON Schema 2020-12 形式（`exclusiveMinimum: N`）に統一する。
    """
    ex = schema.get(exclusive_key)
    if isinstance(ex, bool):
        if ex and isinstance(schema.get(bound_key), (int, float)):
            schema[exclusive_key] = schema.pop(bound_key)
        else:
            schema.pop(exclusive_key, None)
    # 既に数値（3.1形式）または未指定の場合はそのまま


def _merge_all_of(schema: dict) -> None:
    """`allOf` で合成されたスキーマを1つのオブジェクトスキーマにマージする（in-place）。

    このツールが対象とする「ベーススキーマ + 拡張」パターンに限定した簡易マージであり、
    JSON Schema の厳密な合成意味論（矛盾検出等）は扱わない。
    - properties: 全 allOf 要素を単純結合（先勝ち）
    - required: 全 allOf 要素の required を和集合
    - additionalProperties: いずれかが false なら false を継承（安全側に倒す）
    """
    all_of = schema.get("allOf")
    if not isinstance(all_of, list):
        return
    del schema["allOf"]

    merged_properties: dict = dict(schema.get("properties", {}))
    merged_required: list[str] = list(schema.get("required", []))
    additional_properties_false = schema.get("additionalProperties") is False

    for sub in all_of:
        if not isinstance(sub, dict):
            continue
        _merge_all_of(sub)  # ネストした allOf も先に展開しておく

        for k, v in sub.get("properties", {}).items():
            merged_properties.setdefault(k, v)
        for r in sub.get("required", []):
            if r not in merged_required:
                merged_required.append(r)
        if sub.get("additionalProperties") is False:
            additional_properties_false = True

    schema.setdefault("type", "object")
    if merged_properties:
        schema["properties"] = merged_properties
    if merged_required:
        schema["required"] = merged_required
    if additional_properties_false:
        schema["additionalProperties"] = False


def _reduce_one_of_any_of(schema: dict) -> None:
    """`oneOf` / `anyOf` を「代表バリアント（先頭要素）」に還元する（in-place）。

    Layer 1 では全バリアントの組み合わせテストは対象外とし、生成ケースが
    サイレントに0件になることを避けるため、ドキュメント上の代表バリアント
    （先頭要素）に対して構造的な検証を行う。バリアント間の判別・排他性の
    検証自体は対象外（Layer 2 相当）。
    """
    for key in ("oneOf", "anyOf"):
        variants = schema.get(key)
        if not isinstance(variants, list) or not variants:
            continue
        del schema[key]
        first = variants[0]
        if isinstance(first, dict):
            _merge_all_of(first)
            _reduce_one_of_any_of(first)  # 入れ子の oneOf/anyOf も先に展開しておく
            for k, v in first.items():
                schema.setdefault(k, v)
        return


def _walk_schemas(obj: Any, visitor, visited: set[int]) -> None:
    if not isinstance(obj, (dict, list)):
        return
    oid = id(obj)
    if oid in visited:
        return
    visited.add(oid)

    if isinstance(obj, dict):
        if _is_schema_object(obj):
            visitor(obj)
        for v in obj.values():
            _walk_schemas(v, visitor, visited)
    else:
        for v in obj:
            _walk_schemas(v, visitor, visited)


def _is_schema_object(obj: dict) -> bool:
    return any(k in obj for k in ("type", "properties", "items", "allOf", "anyOf", "oneOf"))
