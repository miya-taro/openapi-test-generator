#!/usr/bin/env python3
"""openapi.json + 実DBスキーマから mapping.yaml（generate_db_scenarios.py 用の対応表）の叩き台を生成する。

POST/PUT/PATCH/DELETE の各operationについて、リクエストボディのフィールド名と
DBの各テーブルのカラム名を突き合わせ、最もよく一致するテーブルを推定する。
これはあくまで名前ベースのヒューリスティックであり、精度は100%ではない。
確信度（高/中/低）を必ずコメントで併記するので、低いものは特に人間の確認が必要。
"""
from __future__ import annotations
import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_config, get_postgres_config
from db_introspect import TableInfo, IntrospectionError, introspect_schema
from src.parser import parse_openapi, OpenAPIParseError

_MUTATING_METHODS = ("post", "put", "patch", "delete")
_FUZZY_THRESHOLD = 0.75
_EXACT_SCORE = 1.0
_FUZZY_SCORE = 0.6
_TIE_MARGIN = 0.05  # 次点候補とのスコア差がこれ未満なら「高」確信度を名乗らない

_HEADER = (
    "# 自動生成された叩き台です（generate_mapping.py）。\n"
    "# table はフィールド名とDBカラム名の一致度から推定した「候補」であり、正しいとは限りません。\n"
    "# PHP SQL調査JSONを使った候補も自動承認されません。根拠ファイル/行を確認してください。\n"
    "# 確信度（高/中/低）のコメントを必ず確認し、「低」は特に人間の判断で修正してください。\n"
    "# engine は現時点では全て postgres 前提で出力しています（influxdbは対象外）。\n"
    "# 【重要】外部キーで紐づく子テーブル（例: 注文とその明細行のような親子関係）は、\n"
    "# 1 operation = 1 table 前提のこの自動推定では検出できません。生成後のシナリオYAML\n"
    "# （generate_db_scenarios.py の出力）は子テーブル分のdb_checkが漏れているはずなので、\n"
    "# 必要なら該当operationのtableの下に子テーブルの候補を手動で追記してください\n"
    "# （書き方の実例は examples/mapping.yaml と examples/README.md を参照）。\n\n"
)


@dataclass
class TableScore:
    table: str
    score: float
    matched: int
    exact_matched: int
    total_fields: int


class PHPDBEvidenceError(ValueError):
    """PHP SQL evidence is malformed or does not correspond to the OpenAPI document."""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="openapi.jsonと実DBスキーマからmapping.yamlの叩き台を生成する（PostgreSQLのみ対応）"
    )
    parser.add_argument("openapi_path", help="openapi.json のパス")
    parser.add_argument("--config", required=True, metavar="JSON", help="DB接続情報の設定ファイル")
    parser.add_argument("--schema", default="public", help="対象スキーマ名（省略時: public）")
    parser.add_argument(
        "--php-db-evidence", metavar="JSON",
        help="CopilotがPHPソースから抽出したDBテーブル/カラム候補（任意）",
    )
    parser.add_argument("-o", "--output", default="mapping.yaml.generated", help="出力先YAMLパス")
    args = parser.parse_args()

    try:
        openapi = parse_openapi(args.openapi_path)
    except OpenAPIParseError as e:
        print(f"[ERROR] openapi.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    php_evidence = None
    if args.php_db_evidence:
        try:
            php_evidence = json.loads(Path(args.php_db_evidence).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ERROR] PHP SQL調査結果を読み込めません: {exc}", file=sys.stderr)
            return 1

    try:
        db_config = load_config(args.config)
        pg_config = get_postgres_config(db_config)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] config.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    try:
        schema_info = introspect_schema(pg_config, schema=args.schema)
    except IntrospectionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if not schema_info:
        print(f"[WARN] スキーマ '{args.schema}' にテーブルが見つかりませんでした（0件生成）", file=sys.stderr)
        return 0

    operations = _collect_mutating_operations(openapi)
    guesses = _guess_all(operations, schema_info)
    if php_evidence is not None:
        try:
            guesses = _apply_php_db_evidence(guesses, php_evidence, operations, schema_info)
        except PHPDBEvidenceError as exc:
            print(f"[ERROR] PHP SQL調査結果を利用できません: {exc}", file=sys.stderr)
            return 1

    body = _render_yaml(guesses)
    Path(args.output).write_text(_HEADER + body, encoding="utf-8")
    print(f"[INFO] {len(guesses)} 件のoperation分の候補を {args.output} に出力しました")
    return 0


_SQL_ACTIONS = {"select", "insert", "update", "delete", "upsert", "unknown"}
_SUPPORTED_DB_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_YAML_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def _format_evidence_refs(candidate: dict) -> str:
    refs = [f"{ref['file']}:{ref['line']}" for ref in candidate["evidence"][:5]]
    if len(candidate["evidence"]) > 5:
        refs.append(f"ほか{len(candidate['evidence']) - 5}件")
    return ", ".join(refs)


def _apply_php_db_evidence(
    guesses: list[dict], evidence: object, operations: list[dict], schema_info: dict[str, TableInfo]
) -> list[dict]:
    """Validate Copilot's PHP/SQL candidates against OpenAPI and live DB metadata.

    Even a matching candidate is only medium confidence: source-level SQL behavior and
    dynamic control flow still require a human review.
    """
    if not isinstance(evidence, dict) or evidence.get("format") != "api-tester.php-db-evidence":
        raise PHPDBEvidenceError('format は "api-tester.php-db-evidence" である必要があります')
    _reject_extra_keys(evidence, {"format", "schemaVersion", "operations"}, "ルート")
    schema_version = evidence.get("schemaVersion")
    if (
        not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version != 1
        or not isinstance(evidence.get("operations"), dict)
    ):
        raise PHPDBEvidenceError("schemaVersion または operations の形式が不正です")

    known_operation_ids = {item["operationId"] for item in operations}
    normalized: dict[str, list[dict]] = {}
    for operation_id, operation_evidence in evidence["operations"].items():
        if operation_id not in known_operation_ids:
            raise PHPDBEvidenceError(f"OpenAPIの書き込みoperationIdにありません: {operation_id}")
        if not isinstance(operation_evidence, dict) or not isinstance(operation_evidence.get("tables"), list):
            raise PHPDBEvidenceError(f"{operation_id}: tables は配列で指定してください")
        _reject_extra_keys(operation_evidence, {"tables"}, operation_id)
        candidates = operation_evidence["tables"]
        if not candidates:
            raise PHPDBEvidenceError(f"{operation_id}: tables に候補がありません")

        normalized_candidates = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise PHPDBEvidenceError(f"{operation_id}: table候補がオブジェクトではありません")
            _reject_extra_keys(candidate, {"table", "action", "columns", "evidence"}, operation_id)
            table_name = candidate.get("table")
            action = candidate.get("action")
            columns = candidate.get("columns")
            refs = candidate.get("evidence")
            if not isinstance(table_name, str) or not _SUPPORTED_DB_IDENTIFIER.fullmatch(table_name):
                raise PHPDBEvidenceError(f"{operation_id}: tableは対応するDB識別子形式で指定してください")
            if not isinstance(action, str) or action not in _SQL_ACTIONS:
                raise PHPDBEvidenceError(f"{operation_id}: action は {sorted(_SQL_ACTIONS)} のいずれかです")
            if (
                not isinstance(columns, list) or not columns
                or any(
                    not isinstance(column, str) or not _SUPPORTED_DB_IDENTIFIER.fullmatch(column)
                    for column in columns
                )
                or len(set(columns)) != len(columns)
            ):
                raise PHPDBEvidenceError(f"{operation_id}: columns は空でない重複なしの文字列配列にしてください")
            if not isinstance(refs, list) or not refs:
                raise PHPDBEvidenceError(f"{operation_id}: PHPの根拠ファイルと行番号が必要です")
            normalized_refs = []
            for ref in refs:
                if not isinstance(ref, dict):
                    raise PHPDBEvidenceError(f"{operation_id}: evidenceはfile/lineを持つオブジェクトです")
                _reject_extra_keys(ref, {"file", "line"}, f"{operation_id}: evidence")
                source_file = ref.get("file")
                line = ref.get("line")
                windows_path = PureWindowsPath(source_file) if isinstance(source_file, str) else PureWindowsPath()
                relative_path = PurePosixPath(source_file.replace("\\", "/")) if isinstance(source_file, str) else PurePosixPath()
                if (
                    not isinstance(source_file, str) or not source_file.strip()
                    or any(ord(char) < 32 or char in "\u0085\u2028\u2029" for char in source_file)
                    or windows_path.drive or windows_path.root
                    or relative_path.is_absolute()
                    or ".." in relative_path.parts
                ):
                    raise PHPDBEvidenceError(f"{operation_id}: evidence.file は安全な相対パスで指定してください")
                if not isinstance(line, int) or isinstance(line, bool) or line < 1:
                    raise PHPDBEvidenceError(f"{operation_id}: evidence.line は1以上の整数で指定してください")
                normalized_refs.append({"file": source_file.replace("\\", "/"), "line": line})
            normalized_candidates.append({
                "table": table_name, "action": action, "columns": columns, "evidence": normalized_refs,
            })
        normalized[operation_id] = normalized_candidates

    result = [dict(guess) for guess in guesses]
    by_operation = {guess["operationId"]: guess for guess in result}
    for operation_id, candidates in normalized.items():
        guess = by_operation[operation_id]
        if len(candidates) != 1:
            descriptions = []
            for candidate in candidates:
                actual_table = schema_info.get(candidate["table"])
                if actual_table is None:
                    schema_status = "DBスキーマ未検出"
                else:
                    existing_columns = {column.name for column in actual_table.columns}
                    missing = [column for column in candidate["columns"] if column not in existing_columns]
                    schema_status = "DBスキーマと一致" if not missing else f"DBに無いカラム: {', '.join(missing)}"
                descriptions.append(
                    f"{candidate['table']} ({candidate['action']}: {', '.join(candidate['columns'])}; "
                    f"{schema_status}; 根拠 {_format_evidence_refs(candidate)})"
                )
            guess.update(
                table=None,
                confidence="低",
                note="PHP SQLから複数テーブル候補が見つかりました。対象テーブルを人が選んでください",
                runner_up="; ".join(descriptions),
            )
            continue

        candidate = candidates[0]
        table_name = candidate["table"]
        evidence_text = _format_evidence_refs(candidate)
        actual_table = schema_info.get(table_name)
        if actual_table is None:
            guess.update(
                table=None,
                confidence="低",
                note=(
                    f"PHP候補のテーブル '{table_name}' は接続先DBスキーマにありません "
                    f"(根拠 {evidence_text})"
                ),
                runner_up=guess.get("table"),
            )
            continue

        existing_columns = {column.name for column in actual_table.columns}
        missing_columns = [column for column in candidate["columns"] if column not in existing_columns]
        if missing_columns:
            guess.update(
                table=None,
                confidence="低",
                note=(
                    f"PHP候補のカラムが接続先DBスキーマにありません: {', '.join(missing_columns)} "
                    f"(候補 {table_name}; 根拠 {evidence_text})"
                ),
                runner_up=guess.get("table"),
            )
            continue

        guess.update(
            table=table_name,
            confidence="中",
            note=(
                f"PHP SQL候補: {candidate['action']} {table_name}.{', '.join(candidate['columns'])}; "
                f"根拠 {evidence_text}; DBスキーマと一致。PHPの実行経路は人が確認してください"
            ),
            runner_up=None,
        )
    return result


def _reject_extra_keys(value: dict, allowed: set[str], context: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise PHPDBEvidenceError(f"{context}: 未対応の項目があります: {', '.join(sorted(map(str, extra)))}")


def _collect_mutating_operations(openapi: dict) -> list[dict]:
    """[{operationId, method, path, fields}] のリスト。fieldsはリクエストボディのトップレベル
    プロパティ名（ネストしたobject/arrayは除く。generate_db_scenarios.pyの_flatten_for_dbと同じ理由）。"""
    result = []
    for path, path_item in (openapi.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in _MUTATING_METHODS or not isinstance(op, dict):
                continue
            operation_id = op.get("operationId")
            if not operation_id:
                continue
            result.append(
                {
                    "operationId": operation_id,
                    "method": method,
                    "path": path,
                    "fields": _extract_body_fields(op),
                }
            )
    return result


def _extract_body_fields(op: dict) -> list[str]:
    request_body = op.get("requestBody")
    if not request_body:
        return []
    schema = ((request_body.get("content") or {}).get("application/json") or {}).get("schema")
    if not isinstance(schema, dict):
        return []
    props = schema.get("properties")
    if not isinstance(props, dict):
        return []
    return [
        name for name, sub in props.items()
        if not (isinstance(sub, dict) and sub.get("type") in ("object", "array"))
    ]


def _guess_all(operations: list[dict], schema_info: dict[str, TableInfo]) -> list[dict]:
    guesses = []
    by_base_path: dict[str, str] = {}  # base_path -> 確信度「高」で決まったtable名

    # フィールドがある operation を先に処理し、同一パスの table 推定結果を蓄積する
    with_fields = [op for op in operations if op["fields"]]
    without_fields = [op for op in operations if not op["fields"]]

    for op in with_fields:
        scored = _score_tables(op["fields"], schema_info)
        guess = _build_guess(op, scored)
        guesses.append(guess)
        if guess["table"] is not None and guess["confidence"] in ("高", "中"):
            by_base_path[_resource_key(op["path"])] = guess["table"]

    for op in without_fields:
        base = _resource_key(op["path"])
        if base in by_base_path:
            guesses.append(
                {
                    "operationId": op["operationId"],
                    "table": by_base_path[base],
                    "confidence": "中",
                    "note": "リクエストボディが無いため、同一パスの他operationの推定結果から補完",
                    "runner_up": None,
                }
            )
        else:
            guesses.append(
                {
                    "operationId": op["operationId"],
                    "table": None,
                    "confidence": "低",
                    "note": "リクエストボディが無く、同一パスの他operationからも推定できませんでした",
                    "runner_up": None,
                }
            )

    order = {op["operationId"]: i for i, op in enumerate(operations)}
    guesses.sort(key=lambda g: order[g["operationId"]])
    return guesses


def _resource_key(path: str) -> str:
    """パスから「どのリソースを操作しているか」を表すキーを返す。

    パスパラメータを除いた最後のリテラルセグメントを使う。
    例: /orders -> orders、/orders/{id} -> orders（ordersのコレクション/個別操作は同一リソース）、
    /orders/{id}/lines -> lines（ordersの配下だが別リソース。単純な先頭一致にすると
    /orders/{id} と /orders/{id}/lines を誤って同一視してしまうため、末尾のリテラル
    セグメントで区別する）。
    """
    literals = [seg for seg in path.split("/") if seg and not seg.startswith("{")]
    return literals[-1] if literals else path


def _score_tables(fields: list[str], schema_info: dict[str, TableInfo]) -> list[TableScore]:
    scores = []
    for table_name, table in schema_info.items():
        column_names = [c.name for c in table.columns]
        total = 0.0
        matched = 0
        exact_matched = 0
        for field in fields:
            contribution, is_exact = _best_match_score(field, column_names)
            if contribution > 0:
                matched += 1
                if is_exact:
                    exact_matched += 1
            total += contribution
        scores.append(
            TableScore(
                table=table_name,
                score=total / len(fields) if fields else 0.0,
                matched=matched,
                exact_matched=exact_matched,
                total_fields=len(fields),
            )
        )
    scores.sort(key=lambda s: (-s.score, s.table))
    return scores


def _best_match_score(field: str, column_names: list[str]) -> tuple[float, bool]:
    norm_field = _normalize(field)
    for col in column_names:
        if _normalize(col) == norm_field:
            return _EXACT_SCORE, True
    best_ratio = 0.0
    for col in column_names:
        ratio = difflib.SequenceMatcher(None, norm_field, _normalize(col)).ratio()
        best_ratio = max(best_ratio, ratio)
    if best_ratio >= _FUZZY_THRESHOLD:
        return _FUZZY_SCORE, False
    return 0.0, False


def _normalize(name: str) -> str:
    return re.sub(r"[_\-]", "", name).lower()


def _build_guess(op: dict, scored: list[TableScore]) -> dict:
    if not scored or scored[0].score == 0.0:
        return {
            "operationId": op["operationId"],
            "table": None,
            "confidence": "低",
            "note": "一致するカラムを持つテーブルが見つかりませんでした",
            "runner_up": None,
        }

    best = scored[0]
    confidence = "高" if best.score >= 0.8 else "中" if best.score >= 0.5 else "低"
    note = f"一致 {best.matched}/{best.total_fields} フィールド（うち完全一致 {best.exact_matched} 件）"

    runner_up = None
    if len(scored) > 1 and scored[1].score > 0.0:
        ru = scored[1]
        runner_up = f"{ru.table}（一致 {ru.matched}/{ru.total_fields}, スコア{ru.score:.2f}）"
        # 次点候補とスコアが僅差の場合、テーブル名を一意に決められていないということなので、
        # 個々のフィールド一致度が高くても「高」確信度は名乗らない（複数テーブルが同じ列名を
        # 持つ場合、例えばcart_itemsとorder_itemsが同一のカラム構成を持つ場合に発生する）。
        if confidence == "高" and (best.score - ru.score) < _TIE_MARGIN:
            confidence = "中"
            note += " / 次点候補と僅差のためテーブルを一意に決められません"

    return {
        "operationId": op["operationId"],
        "table": best.table,
        "confidence": confidence,
        "note": note,
        "runner_up": runner_up,
    }


_PLACEHOLDER = "__FILL_ME_IN__"


def _render_yaml(guesses: list[dict]) -> str:
    lines = ["operations:"]
    for g in guesses:
        table = g["table"] or _PLACEHOLDER
        operation_id = str(g["operationId"])
        yaml_key = operation_id if _SAFE_YAML_KEY.fullmatch(operation_id) else json.dumps(operation_id, ensure_ascii=False)
        lines.append(f"  {yaml_key}:")
        lines.append("    engine: postgres")
        lines.append(f"    table: {table}  # 確信度: {g['confidence']}（{g['note']}）")
        if g["runner_up"]:
            lines.append(f"    # 次点候補: {g['runner_up']}")
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
