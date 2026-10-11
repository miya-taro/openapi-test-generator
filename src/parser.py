"""OpenAPI 3.x のパース。

TypeScript版は `@apidevtools/swagger-parser` の `dereference()` を使用していたが、
このプロジェクトで使われる `$ref` は `#/components/...` 形式の内部参照のみのため、
軽量な自前実装で置き換える。
"""
from __future__ import annotations
import copy
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

    api, _ = _resolve_refs(raw, raw, (), {})
    _walk_schemas(api, _normalize_schema, set())

    log.info({"version": version}, "OpenAPI パース完了")
    return api


def _resolve_refs(node: Any, root: dict, stack: tuple[str, ...], cache: dict[str, Any]) -> tuple[Any, bool]:
    """`$ref` を再帰的に展開する。戻り値は (展開結果, tainted)。

    tainted は「この結果のどこかで循環参照による打ち切り（空スキーマ化）が
    発生したか」を表す。循環の打ち切り位置は辿り着いた経路（stack）に依存する
    ため、tainted な結果は同じ $ref の別の参照元では絶対に使い回してはならない。
    tainted でない結果（実務で大半を占める、共有はされるが循環しないスキーマ）
    のみ cache に載せ、同じ $ref を複数箇所から参照した際の再展開コストを避ける。
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if ref in cache:
                return cache[ref], False
            if ref in stack:
                # 循環参照: これ以上展開せず空スキーマとして扱う
                return {}, True
            target = _lookup_ref(ref, root)
            value, tainted = _resolve_refs(target, root, stack + (ref,), cache)
            if not tainted:
                cache[ref] = value
            return value, tainted
        result: dict = {}
        node_tainted = False
        for k, v in node.items():
            resolved, tainted = _resolve_refs(v, root, stack, cache)
            result[k] = resolved
            node_tainted = node_tainted or tainted
        return result, node_tainted
    if isinstance(node, list):
        results = []
        list_tainted = False
        for v in node:
            resolved, tainted = _resolve_refs(v, root, stack, cache)
            results.append(resolved)
            list_tainted = list_tainted or tainted
        return results, list_tainted
    return node, False


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
    _validate_presence_rules(schema)
    _reduce_one_of_any_of(schema)
    _normalize_exclusive_bound(schema, "minimum", "exclusiveMinimum")
    _normalize_exclusive_bound(schema, "maximum", "exclusiveMaximum")
    _normalize_nullable(schema)


def _validate_presence_rules(schema: dict) -> None:
    rules = schema.get("x-otg-presence-rules")
    if rules is None:
        return
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    if not isinstance(rules, list) or not isinstance(properties, dict):
        raise OpenAPIParseError("x-otg-presence-rules はbody項目の配列として指定してください")
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("kind") not in {"atLeastOne", "together"}:
            raise OpenAPIParseError("x-otg-presence-rules のkindが不正です")
        fields = rule.get("fields")
        if (not isinstance(fields, list) or len(fields) != 2 or
                not all(isinstance(name, str) and name in properties for name in fields) or
                fields[0] == fields[1] or any(name in required for name in fields)):
            raise OpenAPIParseError("x-otg-presence-rules には異なる任意body項目を2つ指定してください")


def _normalize_nullable(schema: dict) -> None:
    """OAS 3.0 形式の `nullable: true` を JSON Schema 2020-12 の `type` 配列形式
    （例: `type: "integer"` → `type: ["integer", "null"]`）に変換する。

    `nullable` は JSON Schema 標準のキーワードではなく、`jsonschema` のような汎用
    バリデータには無視される。normalize せずに渡すと、API が正当な null 値を返しても
    レスポンスボディ検証（ランナー側 Level 4）が誤って NG 判定してしまう。
    generator 側（rules/common.py）は元々 `nullable: true` と `type` 配列の "null" の
    両方を見ているため、この変換後も後方互換で動作する。
    """
    if schema.pop("nullable", None) is not True:
        return
    type_ = schema.get("type")
    if isinstance(type_, str):
        schema["type"] = [type_, "null"]
        return
    if isinstance(type_, list):
        if "null" not in type_:
            schema["type"] = [*type_, "null"]
        return

    # type が無い（enum のみ、const のみ、format のみ等）場合、"null" を追加した type
    # 配列だけを付与すると、type の許容集合が {null} だけになり enum/const の許容値と
    # 矛盾して逆に何も通らないスキーマになってしまう（type: object を勝手に補うのも
    # 不正確）。type を触らず、enum/const 側に null を直接含める形にする。
    if "const" in schema:
        schema["enum"] = [schema.pop("const"), None]
    elif isinstance(schema.get("enum"), list) and None not in schema["enum"]:
        schema["enum"] = [*schema["enum"], None]
    # enum も const も無い場合（format のみ等）は、jsonschema は type 未指定なら
    # 既定で null も許容するため、何もしなくてよい。


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
        # $ref 解決のキャッシュにより sub は他の場所と共有されているオブジェクトの
        # 可能性がある（例: 同じコンポーネントスキーマが単独でも別の場所から参照されて
        # いる場合）。deepcopy せずに in-place で書き換えると、無関係な参照先まで
        # 汚染してしまうため、書き換え対象は必ずコピーしてから処理する。
        sub = copy.deepcopy(sub)
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
        discriminator = schema.pop("discriminator", None)
        del schema[key]

        normalized_variants: list[dict] = []
        for v in variants:
            if not isinstance(v, dict):
                continue
            # $ref キャッシュによる共有オブジェクトの可能性があるため、書き換える前に
            # 必ずコピーする（コピーせず in-place で書き換えると、無関係な参照先まで
            # 汚染してしまう）。
            v = copy.deepcopy(v)
            _merge_all_of(v)
            _reduce_one_of_any_of(v)  # 入れ子の oneOf/anyOf も先に展開しておく
            normalized_variants.append(v)
        if not normalized_variants:
            return

        first = normalized_variants[0]
        for k, v in first.items():
            schema.setdefault(k, v)
        if discriminator:
            _apply_discriminator_constraint(schema, discriminator, first)

        # 代表バリアント以外も、`--one-of-full-coverage` 用に正規化済みの形で残しておく
        # （generator/rules/common.py の generate_one_of_variant_cases が参照する）。
        # 標準の JSON Schema キーワードではないため、jsonschema 等の汎用バリデータからは
        # 無視される（未知キーはエラーにならない）。
        if len(normalized_variants) > 1:
            schema["_oneOfVariants"] = normalized_variants
        return


def _apply_discriminator_constraint(schema: dict, discriminator: dict, variant: dict) -> None:
    """discriminator が指定されている場合、選ばれた代表バリアントの判別プロパティに
    enum 制約を補う（既に enum/const があれば触らない）。

    本来は discriminator.mapping やスキーマ名から判別値を特定すべきだが、この時点では
    既に $ref が解決済みでバリアントの元のスキーマ名を追跡できない。そのためバリアントの
    `title`（OpenAPI仕様上、mapping が無い場合の既定の判別値と一致することが多い）を
    使う。title が無ければ制約を補わず、従来通り無制約のまま残す。
    """
    prop_name = discriminator.get("propertyName")
    if not prop_name:
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict) or prop_name not in properties:
        return
    prop_schema = properties[prop_name]
    if not isinstance(prop_schema, dict) or "enum" in prop_schema or "const" in prop_schema:
        return

    variant_title = variant.get("title")
    if variant_title:
        prop_schema["enum"] = [variant_title]


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
    # "type" が無くても正当なスキーマはある（例: enum のみ、format のみで型を暗示する等）。
    # ここに漏れると _walk_schemas に一切訪問されず、nullable（OAS 3.0形式）や
    # exclusiveMinimum/Maximum（bool形式）が正規化されないまま残る。特に nullable の
    # 正規化漏れは深刻で、正当な null 値を返すレスポンスがLevel4検証で誤ってNGになる
    # （jsonschemaは nullable を認識しないため）。normalize対象のキーワードを持つかで判定する。
    return any(
        k in obj
        for k in ("type", "properties", "items", "allOf", "anyOf", "oneOf",
                   "nullable", "enum", "const", "format", "exclusiveMinimum", "exclusiveMaximum")
    )
