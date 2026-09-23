#!/usr/bin/env python3
"""openapi.json + テーブル対応表から、DBシナリオYAML（db_scenario_runner.py 用）の叩き台を生成する。

openapi.json の POST/PUT/PATCH/DELETE（データを変更する操作）を自動で拾い出し、
リクエストボディはスキーマから有効な最小値を自動で埋める。
db_check の table/measurement 名だけは、このツールでは分からないため、
事前に「operationId → テーブル名」の対応表（YAML）を1回用意してもらう。

生成されるYAMLはあくまで叩き台であり、where/columns/tags の内容は
必ず人間が確認・修正すること（コメントで明記される）。
"""
from __future__ import annotations
import argparse
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.parser import parse_openapi, OpenAPIParseError
from request_builder import FORMAT_SAMPLES


class _NoAliasDumper(yaml.SafeDumper):
    """同じ値を where/expect.columns 等で使い回しても &id001/*id001 のような
    YAMLアンカー記法にせず、そのまま値を書き出す（人間が読む前提の叩き台のため）。"""

    def ignore_aliases(self, data) -> bool:
        return True

_MUTATING_METHODS = ("post", "put", "patch", "delete")
_PLACEHOLDER = "__FILL_ME_IN__"

# ライフサイクル順の並び替え（作成→更新、削除は最後）に使う優先度。
# 同じリソースファミリー内で、削除以外はこの順で並べる。
_METHOD_PRIORITY = {"post": 0, "put": 1, "patch": 1}

_HEADER_COMMENT = (
    "# 自動生成された叩き台です。\n"
    "# db_check の table/measurement/where/columns/tags/fields は必ず確認・修正してください。\n"
    f"# {_PLACEHOLDER} となっている箇所は対応表に情報がなかった、または自動では判断できない値です。\n"
    "# シナリオは「リソースファミリー」（例: /orders, /orders/{id}, /orders/{id}/items は\n"
    "# 全て 'orders' ファミリー）ごとにグルーピングし、各ファミリー内は 作成→更新→ネスト作成→…→\n"
    "# 削除（削除は子から先） の順に並べています。ファミリー間の順序も、リクエストボディの\n"
    "# フィールド名（例: categoryId → 'category' ファミリー）から推測した依存関係に基づいて、\n"
    "# 依存先が先に来るよう並べています（あくまで名前ベースの推測のため、必ず確認してください）。\n"
    "# 各ファミリー内の最初のシナリオ以外は、path_params を直前シナリオのレスポンスから\n"
    "# {{response.id}} で引き継ぎます。\n"
    "# scenarios.defaults.engine が大多数のシナリオの既定値です。異なるengineのシナリオのみ\n"
    "# db_check.engine で個別に上書きしています。\n"
    "# 【作成直後の読み取り確認】db_check はAPI呼び出し後のDB変化しか見られず、「作成した\n"
    "# リソースがAPI経由で正しく読み取れるか」（読み取りパス側のバグ）は検証できません。\n"
    "# 対応する単一リソース取得API（例: GET /widgets/{id}）がある場合、作成シナリオの直後に\n"
    "# response_check による読み取り確認シナリオを自動で挿入しています（db_checkは付きません）。\n"
    "# 対応するGET APIが無い、または送信フィールドとレスポンスのキー名が一致しない場合は\n"
    "# 手直しが必要です。\n\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="openapi.json とテーブル対応表からDBシナリオYAMLの叩き台を生成する"
    )
    parser.add_argument("openapi_path", help="openapi.json のパス")
    parser.add_argument("mapping_path", help="operationId → テーブル/measurement 対応表（YAML）のパス")
    parser.add_argument("-o", "--output", default="scenarios.generated.yaml", help="出力先YAMLパス")
    args = parser.parse_args()

    try:
        openapi = parse_openapi(args.openapi_path)
    except OpenAPIParseError as e:
        print(f"[ERROR] openapi.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    mapping_path = Path(args.mapping_path)
    if not mapping_path.exists():
        print(f"[ERROR] 対応表が見つかりません: {mapping_path}", file=sys.stderr)
        return 1
    try:
        mapping_raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(f"[ERROR] 対応表の読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    operations_map = (mapping_raw or {}).get("operations") or {}
    if not operations_map:
        print('[ERROR] 対応表に "operations" セクションがありません', file=sys.stderr)
        return 1

    scenarios = _generate_scenarios(openapi, operations_map)

    if not scenarios:
        print("[WARN] 対応表にマッチする operationId が見つかりませんでした（0件生成）", file=sys.stderr)

    default_engine = _dominant_engine(scenarios)
    defaults: dict = {}
    if default_engine:
        defaults["engine"] = default_engine
        for scenario in scenarios:
            # response_check のみのシナリオ（作成直後の読み取り確認）には db_check が無い
            db_check = scenario.get("db_check")
            if db_check and db_check.get("engine") == default_engine:
                del db_check["engine"]

    output = {"scenarios": {"defaults": defaults, "list": scenarios}}
    body = yaml.dump(output, allow_unicode=True, sort_keys=False, Dumper=_NoAliasDumper)
    Path(args.output).write_text(_HEADER_COMMENT + body, encoding="utf-8")
    print(f"[INFO] {len(scenarios)} 件のシナリオ雛形を {args.output} に出力しました")
    return 0


def _dominant_engine(scenarios: list[dict]) -> str | None:
    """生成されたシナリオ群の中で最も多い engine を返す（同数なら postgres を優先）。
    1件もなければ None。scenarios.defaults.engine の値として使う。"""
    engines = [s["db_check"]["engine"] for s in scenarios if "engine" in s.get("db_check", {})]
    if not engines:
        return None
    counts = Counter(engines)
    max_count = max(counts.values())
    candidates = [engine for engine, count in counts.items() if count == max_count]
    return "postgres" if "postgres" in candidates else candidates[0]


def _resource_family(path: str) -> str:
    """path からリソースファミリーのキーを導出する。

    例: /orders, /orders/{id}, /orders/{id}/items は全て "orders" ファミリーにまとめる
    （最初の非path-paramセグメントを使う）。これにより、親リソースとその子リソース
    （注文明細等）への操作を同じファミリーとして連鎖できる。
    """
    for seg in path.strip("/").split("/"):
        if seg and not (seg.startswith("{") and seg.endswith("}")):
            return seg
    return path


def _path_depth(path: str) -> int:
    return len([s for s in path.strip("/").split("/") if s])


def _collect_body_field_names(schema: dict | None, depth: int = 0, max_depth: int = 2) -> list[str]:
    """requestBody のフィールド名を、ネストしたobject/array要素も含めて浅く収集する
    （リソースファミリー間の依存関係を推測する材料にする。例: createOrder の
    items[].productId から "products" ファミリーへの依存を検出する）。"""
    if not isinstance(schema, dict) or depth > max_depth:
        return []
    names: list[str] = []
    for name, prop_schema in (schema.get("properties") or {}).items():
        names.append(name)
        if not isinstance(prop_schema, dict):
            continue
        if prop_schema.get("type") == "object":
            names.extend(_collect_body_field_names(prop_schema, depth + 1, max_depth))
        elif prop_schema.get("type") == "array":
            items = prop_schema.get("items")
            if isinstance(items, dict):
                names.extend(_collect_body_field_names(items, depth + 1, max_depth))
    return names


_ES_PLURAL_SAFE_SUFFIXES = ("ss", "x", "ch", "sh")


def _singularize(name: str) -> str:
    # 英語の複数形からの簡易単数化。"categories" → "category" のような -ies → -y は
    # 素朴な末尾"s"除去では "categorie" になってしまい、"categoryId" 等のフィールド名
    # からの参照推測にマッチしなくなるため、この不規則パターンだけ個別に対応する。
    if name.endswith("ies") and len(name) > 3:
        return name[:-3] + "y"
    # 同様に、"addresses" → "address"（末尾が ss/x/ch/sh の語は -es で複数形になる）も
    # 素朴な末尾"s"除去1文字だけでは "addresse" になってしまう。ただし "status" のように
    # 単独の "s" で終わる語（statuses）は、この-es除去2文字にするとcase/casesのような
    # "e"で終わる語（cases → 誤って "cas" になる）と区別がつかない曖昧なケースのため、
    # 誤検出が無いと確認できる ss/x/ch/sh の場合のみ対応する（statusesは既知の未対応）。
    if name.endswith("es") and len(name) > 2 and name[:-2].endswith(_ES_PLURAL_SAFE_SUFFIXES):
        return name[:-2]
    if name.endswith("s") and len(name) > 1:
        return name[:-1]
    return name


def _infer_referenced_family(field_name: str, singular_to_family: dict[str, str], self_family: str) -> str | None:
    """フィールド名（例: "categoryId" / "category_id"）から、参照先と推測される
    リソースファミリー名を返す。自分自身のファミリーを指す場合や、対応表に無い
    ファミリーを指す場合は None。"""
    lname = field_name.lower()
    if lname == "id" or not lname.endswith("id"):
        return None
    base = field_name[:-2].rstrip("_").lower()
    candidate = singular_to_family.get(base)
    if candidate and candidate != self_family:
        return candidate
    return None


def _order_families(
    families: dict[str, list[tuple[str, str, str, dict]]], operations_map: dict
) -> list[str]:
    """リソースファミリーを、名前ベースで推測した依存関係（依存先が先）で並び替える。

    推測はあくまでヒューリスティック（フィールド名からの当て推量）のため、
    循環が生じて順序を確定できないファミリーは末尾にアルファベット順で追加する。
    """
    family_names = set(families.keys())
    singular_to_family = {_singularize(name): name for name in family_names}

    deps: dict[str, set[str]] = {name: set() for name in family_names}
    for family, items in families.items():
        for _path, _method, operation_id, op in items:
            mapping = operations_map.get(operation_id) or {}
            if mapping.get("engine") == "influxdb":
                continue  # InfluxDBはリレーション概念が無いため対象外
            body_schema = _resolve_json_body_schema(op)
            for field_name in _collect_body_field_names(body_schema):
                ref = _infer_referenced_family(field_name, singular_to_family, family)
                if ref:
                    deps[family].add(ref)

    ordered: list[str] = []
    remaining = {name: set(d) for name, d in deps.items()}
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not d)
        if not ready:
            break  # 循環依存（名前ベースの推測なので誤検出の可能性もある）
        ordered.extend(ready)
        for n in ready:
            del remaining[n]
        for d in remaining.values():
            d.difference_update(ready)

    if remaining:
        print(
            f"[WARN] リソースファミリー間の依存関係が循環しているため、"
            f"以下は推測順序を確定できませんでした（末尾にアルファベット順で配置）: {sorted(remaining)}",
            file=sys.stderr,
        )
        ordered.extend(sorted(remaining))

    return ordered


def _generate_scenarios(openapi: dict, operations_map: dict) -> list[dict]:
    candidates: list[tuple[str, str, str, dict]] = []
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in _MUTATING_METHODS or not isinstance(op, dict):
                continue
            operation_id = op.get("operationId")
            if not operation_id or operation_id not in operations_map:
                continue
            candidates.append((path, method, operation_id, op))

    families: dict[str, list[tuple[str, str, str, dict]]] = {}
    for item in candidates:
        families.setdefault(_resource_family(item[0]), []).append(item)

    scenarios: list[dict] = []
    for family in _order_families(families, operations_map):
        items = families[family]
        # ファミリー内は「作成→更新→ネスト作成→…」を先に、削除は最後（子から先）に並べる。
        non_delete = [i for i in items if i[1] != "delete"]
        delete_items = [i for i in items if i[1] == "delete"]
        non_delete.sort(key=lambda i: (_path_depth(i[0]), _METHOD_PRIORITY.get(i[1], 1)))
        delete_items.sort(key=lambda i: -_path_depth(i[0]))
        ordered_items = non_delete + delete_items

        family_scenarios: list[dict] = []
        for index, (path, method, operation_id, op) in enumerate(ordered_items):
            mapping = operations_map[operation_id] or {}
            is_first_in_family = index == 0
            family_scenarios.append(_build_scenario(operation_id, method, path, op, mapping, is_first_in_family))

        # db_check は「APIを呼んだ後にDBがどう変化したか」しか見られず、「作成したリソースが
        # API経由で正しく読み取れるか」（読み取りパス側のバグ）は検証できない。作成直後に
        # 対応する GET（単一リソース取得）があれば、送信したフィールドがそのまま読み取れるかを
        # response_check で確認するシナリオを自動で挿入する。
        if ordered_items and ordered_items[0][1] == "post" and family_scenarios[0]["request"].get("body"):
            get_info = _find_get_by_id_operation(openapi, family)
            if get_info:
                read_check = _build_read_verification_scenario(*get_info, family_scenarios[0]["request"]["body"])
                family_scenarios.insert(1, read_check)

        scenarios.extend(family_scenarios)

    return scenarios


def _find_get_by_id_operation(openapi: dict, family: str) -> tuple[str, dict] | None:
    """このファミリーの「単一リソース取得」操作（例: GET /orders/{id}）を探す。
    requestBodyを持たず、path paramをちょうど1つだけ持つGET操作のみを対象とする
    （一覧取得や複数キーでの取得は対象外）。"""
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict) or _resource_family(path) != family:
            continue
        get_op = path_item.get("get")
        if not isinstance(get_op, dict) or get_op.get("requestBody"):
            continue
        operation_id = get_op.get("operationId")
        if not operation_id:
            continue
        path_params = [p for p in (get_op.get("parameters") or []) if isinstance(p, dict) and p.get("in") == "path"]
        if len(path_params) != 1:
            continue
        return operation_id, get_op
    return None


def _build_read_verification_scenario(get_operation_id: str, get_op: dict, created_body: dict) -> dict:
    path_params = {}
    for p in get_op.get("parameters") or []:
        if isinstance(p, dict) and p.get("in") == "path":
            name = p.get("name")
            if name:
                path_params[name] = "{{response.id}}"

    return {
        "name": f"{get_operation_id}（自動生成・作成直後の読み取り確認・要確認）",
        "request": {"operationId": get_operation_id, "path_params": path_params},
        "response_check": {
            "expect": {
                "status": 200,
                "body": _flatten_for_db(created_body),
            }
        },
    }


def _resolve_json_body_schema(op: dict) -> dict | None:
    request_body = op.get("requestBody")
    if not request_body:
        return None
    return ((request_body.get("content") or {}).get("application/json") or {}).get("schema")


def _build_scenario(
    operation_id: str, method: str, path: str, op: dict, mapping: dict, is_first_in_family: bool
) -> dict:
    is_delete = method == "delete"

    path_params = _build_path_params(op, is_first_in_family)
    body = {} if is_delete else _build_request_body(op)

    engine = mapping.get("engine", "postgres")
    db_check = _build_postgres_check(body, is_delete, mapping) if engine == "postgres" \
        else _build_influx_check(body, mapping)

    request: dict = {"operationId": operation_id}
    if path_params:
        request["path_params"] = path_params
    if body:
        request["body"] = body

    return {
        "name": f"{operation_id}（自動生成・要確認）",
        "request": request,
        "db_check": db_check,
    }


def _build_postgres_check(body: dict, is_delete: bool, mapping: dict) -> dict:
    table = mapping.get("table", _PLACEHOLDER)
    if is_delete:
        return {
            "engine": "postgres",
            "table": table,
            "where": {"id": "{{response.id}}"},
            "expect": {"exists": False},
        }
    flat = _flatten_for_db(body)
    return {
        "engine": "postgres",
        "table": table,
        "where": flat if flat else {"id": _PLACEHOLDER},
        "expect": {"exists": True, "columns": dict(flat)},
    }


def _build_influx_check(body: dict, mapping: dict) -> dict:
    measurement = mapping.get("measurement", _PLACEHOLDER)
    tag_fields = mapping.get("tags") or []
    flat = _flatten_for_db(body)
    tags = {k: v for k, v in flat.items() if k in tag_fields}
    fields = {k: v for k, v in flat.items() if k not in tag_fields}
    return {
        "engine": "influxdb",
        "measurement": measurement,
        "tags": tags,
        "time_range": "5m",
        "expect": {"exists": True, "fields": fields},
    }


def _flatten_for_db(body: dict) -> dict:
    """where/columns/fields の叩き台として使えるスカラー値のみを残す。

    - ネストしたオブジェクト・配列は単純な "カラム = 値" の一致条件にならないため除外する
      （別テーブルへのリレーションである可能性が高く、自動では対応できない）
    - "id" は多くの場合サーバー側の自動採番で上書きされ、送信した値とは一致しないため除外する
    """
    return {
        k: v for k, v in body.items()
        if k != "id" and not isinstance(v, (dict, list))
    }


def _scenario_baseline(schema: dict) -> object:
    """シナリオ生成用のベースライン値を組み立てる。

    request_builder.py の _expand_value（Layer 1用、required フィールドのみ埋める
    "最小有効リクエスト"）とは違い、こちらは object 型なら required の有無に関わらず
    可能な限り全プロパティを埋める。required を1つも宣言していないスキーマ
    （実務のOpenAPIでもよくある）でも、DBシナリオの叩き台として意味のある
    値を持つリクエストボディにするため。
    """
    # スキーマに default が明示されていれば、型ベースの適当な値より優先する。
    if "default" in schema:
        return schema["default"]

    t = schema.get("type", "string")
    fmt = schema.get("format", "")
    enum = schema.get("enum")

    if enum:
        return enum[0]
    if t in ("integer", "number"):
        minimum = schema.get("minimum")
        return minimum if minimum is not None else 1
    if t == "boolean":
        return True
    if t == "array":
        items = schema.get("items", {})
        return [_scenario_baseline(items)]
    if t == "object":
        props = schema.get("properties", {})
        # readOnly なプロパティ（サーバー側専用）はリクエストボディには含めない
        # readOnly なプロパティ（サーバー側専用）はリクエストボディには含めない
        return {k: _scenario_baseline(v) for k, v in props.items() if not v.get("readOnly")}

    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len
    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]
    return "test"


def _build_request_body(op: dict) -> dict:
    schema = _resolve_json_body_schema(op)
    if not schema:
        return {}
    value = _scenario_baseline(schema)
    return value if isinstance(value, dict) else {}


def _build_path_params(op: dict, is_first_in_family: bool) -> dict:
    result: dict = {}
    for p in op.get("parameters") or []:
        if not isinstance(p, dict) or p.get("in") != "path":
            continue
        name = p.get("name")
        if not name:
            continue
        if is_first_in_family:
            # ファミリー内で最初のシナリオ（多くの場合トップレベルの作成操作）は、
            # 引き継ぎ元となる直前のシナリオが無いためベースライン値で埋める。
            result[name] = _scenario_baseline(p.get("schema") or {})
        else:
            # 2件目以降は、直前のシナリオ（同ファミリー内、作成→更新→ネスト作成の順）の
            # レスポンスから既存リソースのIDを引き継ぐ想定のプレースホルダにする。
            result[name] = "{{response.id}}"
    return result


if __name__ == "__main__":
    sys.exit(main())
