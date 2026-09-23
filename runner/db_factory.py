"""シナリオの前提データ（given）をDBに直接INSERTする「factory」。

APIチェーン（{{response.xxx}}）だけでは、そもそも作成用のAPIエンドポイントが
存在しないリソース（SSO連携・他サービスからのイベント連携・管理画面経由でしか
作られないリソース等）の前提データを用意できない。このモジュールはDBスキーマ
（NOT NULL制約・enum・CHECK制約等）から未指定の必須カラムを自動で埋めて直接INSERTし、
生成された行（自動採番されたID等を含む）をそのまま返す
（request_builder.py が OpenAPI スキーマから baseline を埋めるのと同じ考え方）。

対応はPostgreSQLのみ（db_introspect.pyと同じ制約）。
"""
from __future__ import annotations
import datetime
import re

import psycopg2
import psycopg2.extras

from db_introspect import CheckConstraintInfo, ColumnInfo, introspect_schema

_TEXT_TYPES = {"character varying", "text", "character", "char"}
_NUMERIC_TYPES = {"integer", "bigint", "smallint", "numeric", "decimal", "real", "double precision"}
_IDENT_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FactoryError(Exception):
    pass


def _quote_ident(name: str) -> str:
    # table/column 名はシナリオYAML作成者が指定する値（table）や実DBから読み取った値
    # （column）だが、SQL文字列への直接埋め込みになるため、識別子として妥当な文字のみ許可する
    # （postgres_backend.py と同じ方針）。
    if not _IDENT_PATTERN.match(name):
        raise FactoryError(f"不正な識別子です: {name!r}")
    return f'"{name}"'


def create(pg_config: dict, table: str, fields: dict, schema: str = "public") -> tuple[dict, dict]:
    """table に fields をベースにINSERTする。

    戻り値: (INSERTされた行全体の辞書, 主キーカラム->値の辞書（後始末の削除に使う）)

    fields で指定されなかった NOT NULL かつ DB側デフォルトが無いカラムは、列の型・enum・
    CHECK制約から機械的に妥当な値を補って埋める。自動採番列（SERIAL/IDENTITY）は
    fields に指定されていても無視する（DBに採番させる）。
    """
    tables = introspect_schema(pg_config, tables=[table], schema=schema)
    info = tables.get(table)
    if info is None:
        raise FactoryError(f"テーブルが見つかりません: {table}")

    check_by_column = {cc.column: cc for cc in info.check_constraints}
    values: dict = {}
    for col in info.columns:
        if col.is_auto_generated:
            continue  # 明示指定されていてもDBに採番させる
        if col.name in fields:
            values[col.name] = fields[col.name]
            continue
        must_include = not col.is_nullable and col.column_default is None
        if not must_include:
            continue
        values[col.name] = _placeholder_value(col, check_by_column.get(col.name))

    if not values:
        raise FactoryError(f"'{table}' にINSERTするカラムがありません（fieldsを指定してください）")

    columns = list(values.keys())
    col_list = ", ".join(_quote_ident(c) for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))

    conn = psycopg2.connect(**pg_config)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f'INSERT INTO {_quote_ident(table)} ({col_list}) VALUES ({placeholders}) RETURNING *',
                [values[c] for c in columns],
            )
            row = dict(cur.fetchone())
        conn.commit()
    except psycopg2.Error as e:
        conn.rollback()
        raise FactoryError(f"'{table}' への前提データ投入に失敗しました: {e}") from e
    finally:
        conn.close()

    primary_key = {col: row[col] for col in info.primary_key if col in row}
    return row, primary_key


def delete(pg_config: dict, table: str, primary_key: dict, schema: str = "public") -> None:
    """create() が作った行を主キーで削除する。primary_key が空の場合は何もしない。"""
    if not primary_key:
        return
    conditions = " AND ".join(f"{_quote_ident(k)} = %s" for k in primary_key)
    conn = psycopg2.connect(**pg_config)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {_quote_ident(table)} WHERE {conditions}", list(primary_key.values()))
        conn.commit()
    finally:
        conn.close()


def _placeholder_value(col: ColumnInfo, check: CheckConstraintInfo | None) -> object:
    if col.enum_values:
        return col.enum_values[0]
    if check is not None and check.allowed_values:
        return check.allowed_values[0]

    dt = col.data_type
    if dt in _NUMERIC_TYPES:
        return 1
    if dt == "boolean":
        return True
    if dt in _TEXT_TYPES:
        text = f"factory_{col.name}"
        if col.character_maximum_length is not None:
            text = text[: col.character_maximum_length]
        return text
    if dt == "date":
        return datetime.date.today()
    if dt in ("timestamp without time zone", "timestamp with time zone"):
        return datetime.datetime.now()
    if dt == "uuid":
        return "00000000-0000-0000-0000-000000000001"
    if dt in ("json", "jsonb"):
        return psycopg2.extras.Json({})
    if col.udt_name.startswith("_"):  # 配列型（例: _text, _int4）
        return []
    raise FactoryError(
        f"'{col.name}'（type={dt}）の値を自動生成できません。given.fields で明示的に指定してください。"
    )
