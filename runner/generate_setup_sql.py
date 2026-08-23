#!/usr/bin/env python3
"""実DBのスキーマ（information_schema/pg_catalog）から setup.sql / teardown.sql の雛形を生成する。

外部キー制約を満たすINSERT順序（親→子）とTRUNCATE順序（子→親）は自動で決定する。
NOT NULL列には型・enum・単純なCHECK制約（IN(...)相当）を踏まえた仮値を入れる。
生成されるのはあくまで「実行してエラーにならない雛形」であり、値の意味（実際に
テストで使いたいデータかどうか）は必ず人間が確認・修正すること。
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import load_config, get_postgres_config
from db_introspect import (
    ColumnInfo,
    CheckConstraintInfo,
    TableInfo,
    IntrospectionError,
    introspect_schema,
    topological_order,
)

_HEADER = (
    "-- 自動生成された雛形です（generate_setup_sql.py）。\n"
    "-- FK制約を満たすINSERT順序は自動計算されていますが、値の中身（実際に意味のある\n"
    "-- テストデータかどうか）は必ず人間が確認・修正してください。\n"
    "-- PRIMARY KEYは全テーブルで id=1 を仮定しています。複数行必要な場合や、他の値と\n"
    "-- 衝突する場合は調整してください。\n\n"
)

_SEED_ID = 1  # 生成する各テーブル1行分の仮PK値。全テーブル共通にすることでFK参照を単純化する。


def main() -> int:
    parser = argparse.ArgumentParser(
        description="実DBのスキーマからsetup.sql/teardown.sqlの雛形を生成する（PostgreSQLのみ対応）"
    )
    parser.add_argument("--config", required=True, metavar="JSON", help="DB接続情報の設定ファイル")
    parser.add_argument("--schema", default="public", help="対象スキーマ名（省略時: public）")
    parser.add_argument(
        "--tables", metavar="T1,T2,...",
        help="対象テーブル名（カンマ区切り）。省略時はスキーマ内の全テーブルが対象",
    )
    parser.add_argument("--setup-output", default="setup.sql.generated", help="setup.sql の出力先")
    parser.add_argument("--teardown-output", default="teardown.sql.generated", help="teardown.sql の出力先")
    args = parser.parse_args()

    try:
        db_config = load_config(args.config)
        pg_config = get_postgres_config(db_config)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] config.json の読み込みに失敗しました: {e}", file=sys.stderr)
        return 1

    tables = [t.strip() for t in args.tables.split(",")] if args.tables else None

    try:
        schema_info = introspect_schema(pg_config, tables=tables, schema=args.schema)
    except IntrospectionError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if not schema_info:
        print(f"[WARN] スキーマ '{args.schema}' にテーブルが見つかりませんでした（0件生成）", file=sys.stderr)
        return 0

    ordered, unresolved = topological_order(schema_info)
    if unresolved:
        print(
            f"[WARN] 循環参照のためINSERT順序を自動決定できないテーブルがあります: {unresolved}"
            "（手動で順序を確認してください）",
            file=sys.stderr,
        )
    all_names = ordered + unresolved  # unresolved分は末尾にベストエフォートで追加

    setup_sql = _build_setup_sql(schema_info, all_names)
    teardown_sql = _build_teardown_sql(all_names)

    Path(args.setup_output).write_text(setup_sql, encoding="utf-8")
    Path(args.teardown_output).write_text(teardown_sql, encoding="utf-8")
    print(f"[INFO] {len(all_names)} テーブル分の雛形を {args.setup_output} / {args.teardown_output} に出力しました")
    return 0


def _build_teardown_sql(ordered_names: list[str]) -> str:
    lines = [f'TRUNCATE TABLE "{name}" RESTART IDENTITY CASCADE;' for name in reversed(ordered_names)]
    return "\n".join(lines) + "\n"


def _build_setup_sql(schema_info: dict[str, TableInfo], ordered_names: list[str]) -> str:
    parts = [_HEADER, _build_teardown_sql(ordered_names), "\n"]
    for name in ordered_names:
        parts.append(_build_insert(schema_info[name]))
    return "".join(parts)


def _build_insert(table: TableInfo) -> str:
    warnings = _unresolved_check_warnings(table)
    columns, values, comments = _select_columns_and_values(table)

    lines = list(warnings)
    col_list = ", ".join(f'"{c}"' for c in columns)
    val_list = ", ".join(values)
    comment_suffix = f"  -- {'; '.join(comments)}" if comments else ""
    lines.append(f'INSERT INTO "{table.name}" ({col_list}) VALUES')
    lines.append(f"  ({val_list});{comment_suffix}")
    lines.append("")
    return "\n".join(lines)


def _unresolved_check_warnings(table: TableInfo) -> list[str]:
    warnings = []
    for cc in table.check_constraints:
        if cc.allowed_values is None:
            warnings.append(
                f'-- WARNING: "{table.name}"."{cc.column}" にCHECK制約がありますが、'
                f"許容値を自動判定できませんでした。仮値がエラーになる可能性があります: {cc.check_clause}"
            )
    return warnings


def _select_columns_and_values(table: TableInfo) -> tuple[list[str], list[str], list[str]]:
    """(INSERT対象カラム名, 対応するSQLリテラル, FK等の補足コメント) を返す。

    含めるカラム: PRIMARY KEY / FOREIGN KEY（常に含める。値を予測可能にするため）、
    および NOT NULL かつ DB側デフォルトが無い列（省略するとINSERTがエラーになるため）。
    それ以外（NULL許容、またはデフォルトあり）は雛形を簡潔にするため省略する。
    """
    fk_by_column = {fk.column: fk for fk in table.foreign_keys}
    check_by_column = {cc.column: cc for cc in table.check_constraints}

    columns: list[str] = []
    values: list[str] = []
    comments: list[str] = []

    for col in table.columns:
        is_pk = col.name in table.primary_key
        fk = fk_by_column.get(col.name)
        must_include = is_pk or fk is not None or (not col.is_nullable and col.column_default is None)
        if not must_include:
            continue

        if is_pk:
            value = str(_SEED_ID)
        elif fk is not None:
            value = str(_SEED_ID)  # 参照先テーブルも同じ仮PK値(_SEED_ID)で1行だけ生成しているため
            self_ref = " (自己参照)" if fk.ref_table == table.name else ""
            comments.append(f"FK: {col.name} -> {fk.ref_table}.{fk.ref_column}{self_ref}")
        else:
            value = _placeholder_value(col, check_by_column.get(col.name))

        columns.append(col.name)
        values.append(value)

    return columns, values, comments


_TEXT_TYPES = {"character varying", "text", "character", "char"}
_NUMERIC_TYPES = {
    "integer", "bigint", "smallint", "numeric", "decimal", "real", "double precision",
}


def _placeholder_value(col: ColumnInfo, check: "CheckConstraintInfo | None") -> str:
    if col.enum_values:
        return _sql_string(col.enum_values[0])
    if check is not None and check.allowed_values:
        return _sql_string(check.allowed_values[0])

    dt = col.data_type
    if dt in _NUMERIC_TYPES:
        return "1"
    if dt == "boolean":
        return "true"
    if dt in _TEXT_TYPES:
        text = f"placeholder_{col.name}"
        if col.character_maximum_length is not None:
            text = text[: col.character_maximum_length]
        return _sql_string(text)
    if dt == "date":
        return "CURRENT_DATE"
    if dt in ("timestamp without time zone", "timestamp with time zone"):
        return "now()"
    if dt == "uuid":
        return "'00000000-0000-0000-0000-000000000001'"
    if dt == "json":
        return "'{}'::json"
    if dt == "jsonb":
        return "'{}'::jsonb"
    if col.udt_name.startswith("_"):  # 配列型（例: _text, _int4）
        return "'{}'"
    return "NULL"  # 未対応の型: 手動での修正が前提


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


if __name__ == "__main__":
    sys.exit(main())
