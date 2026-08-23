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
import copy
import sys
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

_HEADER_COMMENT = (
    "# 自動生成された叩き台です。\n"
    "# db_check の table/measurement/where/columns/tags/fields は必ず確認・修正してください。\n"
    f"# {_PLACEHOLDER} となっている箇所は対応表に情報がなかった、または自動では判断できない値です。\n"
    "# update/delete 系の path_params は多くの場合、直前の作成シナリオのレスポンスから\n"
    "# {{response.id}} で引き継ぐ想定です（シナリオの順序を調整してください）。\n\n"
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

    body = yaml.dump({"scenarios": scenarios}, allow_unicode=True, sort_keys=False, Dumper=_NoAliasDumper)
    Path(args.output).write_text(_HEADER_COMMENT + body, encoding="utf-8")
    print(f"[INFO] {len(scenarios)} 件のシナリオ雛形を {args.output} に出力しました")
    return 0


def _generate_scenarios(openapi: dict, operations_map: dict) -> list[dict]:
    scenarios: list[dict] = []
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in _MUTATING_METHODS or not isinstance(op, dict):
                continue
            operation_id = op.get("operationId")
            if not operation_id or operation_id not in operations_map:
                continue
            mapping = operations_map[operation_id] or {}
            scenarios.append(_build_scenario(operation_id, method, path, op, mapping))
    return scenarios


def _build_scenario(operation_id: str, method: str, path: str, op: dict, mapping: dict) -> dict:
    is_delete = method == "delete"
    is_create = method == "post"

    path_params = _build_path_params(op, is_create)
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
        return {k: _scenario_baseline(v) for k, v in props.items()}

    min_len = schema.get("minLength")
    if min_len and min_len > 0:
        return "a" * min_len
    if fmt in FORMAT_SAMPLES:
        return FORMAT_SAMPLES[fmt]
    return "test"


def _build_request_body(op: dict) -> dict:
    request_body = op.get("requestBody")
    if not request_body:
        return {}
    schema = ((request_body.get("content") or {}).get("application/json") or {}).get("schema")
    if not schema:
        return {}
    value = _scenario_baseline(schema)
    return value if isinstance(value, dict) else {}


def _build_path_params(op: dict, is_create: bool) -> dict:
    result: dict = {}
    for p in op.get("parameters") or []:
        if not isinstance(p, dict) or p.get("in") != "path":
            continue
        name = p.get("name")
        if not name:
            continue
        if is_create:
            result[name] = _scenario_baseline(p.get("schema") or {})
        else:
            # update/delete は既存リソースのIDが必要になることが多いため、
            # 直前の作成シナリオのレスポンスから引き継ぐことを想定したプレースホルダにする
            result[name] = "{{response.id}}"
    return result


if __name__ == "__main__":
    sys.exit(main())
