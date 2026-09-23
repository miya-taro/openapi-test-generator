"""PostgreSQLの実DBスキーマをinformation_schema/pg_catalogから読み取る共通処理。

generate_setup_sql.py（setup.sql雛形生成）と generate_mapping.py（mapping.yaml叩き台生成）
の両方から使う。DB接続はpsycopg2、対象はPostgreSQLのみ（--setup/--teardownと同じ制約）。
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

import psycopg2
import psycopg2.extras

# check_clause から "IN (...)" 相当の許容値を抜き出すための正規表現。
# PostgreSQLは `CHECK (col IN ('a','b'))` を内部的に
# `(col)::text = ANY ((ARRAY['a'::character varying, ...])::text[])` のような形に正規化するため、
# ARRAY[...] の中の文字列リテラルを拾う。
_ARRAY_LITERALS_RE = re.compile(r"ARRAY\[(.*?)\]")
# PostgreSQLのSQL標準文字列リテラルは、埋め込まれた ' を \' ではなく '' (二重化)で
# エスケープする（standard_conforming_strings のデフォルト設定に関わらず、
# information_schema.check_constraints.check_clause の描画は常にこの形式）。
_STRING_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'")
_NOT_NULL_CLAUSE_RE = re.compile(r"IS NOT NULL", re.IGNORECASE)


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    udt_name: str
    is_nullable: bool
    column_default: str | None
    enum_values: list[str] | None = None
    character_maximum_length: int | None = None

    @property
    def is_auto_generated(self) -> bool:
        """SERIAL/IDENTITY列（DBが値を自動採番する）かどうか。"""
        if not self.column_default:
            return False
        return "nextval(" in self.column_default


@dataclass
class ForeignKeyInfo:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class CheckConstraintInfo:
    column: str
    check_clause: str
    allowed_values: list[str] | None  # IN(...)相当を検出できた場合のみ


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    check_constraints: list[CheckConstraintInfo] = field(default_factory=list)

    def column(self, name: str) -> ColumnInfo | None:
        return next((c for c in self.columns if c.name == name), None)


class IntrospectionError(Exception):
    pass


def introspect_schema(
    pg_config: dict, tables: list[str] | None = None, schema: str = "public"
) -> dict[str, TableInfo]:
    """指定テーブル（省略時は対象スキーマの全テーブル）のスキーマ情報を取得する。

    tables を指定した場合でも、外部キーで参照している親テーブルが指定漏れしていれば
    自動的に追加で読み込む（setup.sql生成にはFK先のテーブル情報が必須のため）。
    """
    conn = psycopg2.connect(**pg_config)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            target_names = set(tables) if tables else _list_all_tables(cur, schema)
            if tables:
                _validate_tables_exist(cur, schema, target_names)

            result: dict[str, TableInfo] = {}
            pending = set(target_names)
            while pending:
                name = pending.pop()
                if name in result:
                    continue
                info = _load_table(cur, schema, name)
                result[name] = info
                for fk in info.foreign_keys:
                    if fk.ref_table != name and fk.ref_table not in result:
                        pending.add(fk.ref_table)
            return result
    finally:
        conn.close()


def _list_all_tables(cur, schema: str) -> set[str]:
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (schema,),
    )
    return {row["table_name"] for row in cur.fetchall()}


def _validate_tables_exist(cur, schema: str, names: set[str]) -> None:
    existing = _list_all_tables(cur, schema)
    missing = names - existing
    if missing:
        raise IntrospectionError(f"スキーマ '{schema}' にテーブルが見つかりません: {sorted(missing)}")


def _load_table(cur, schema: str, name: str) -> TableInfo:
    info = TableInfo(name=name)
    info.columns = _load_columns(cur, schema, name)
    info.primary_key = _load_primary_key(cur, schema, name)
    info.foreign_keys = _load_foreign_keys(cur, schema, name)
    info.check_constraints = _load_check_constraints(cur, schema, name)
    return info


def _load_columns(cur, schema: str, name: str) -> list[ColumnInfo]:
    cur.execute(
        "SELECT column_name, data_type, udt_name, is_nullable, column_default, character_maximum_length "
        "FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, name),
    )
    columns = []
    for row in cur.fetchall():
        enum_values = None
        if row["data_type"] == "USER-DEFINED":
            enum_values = _load_enum_values(cur, row["udt_name"])
        columns.append(
            ColumnInfo(
                name=row["column_name"],
                data_type=row["data_type"],
                udt_name=row["udt_name"],
                is_nullable=row["is_nullable"] == "YES",
                column_default=row["column_default"],
                enum_values=enum_values,
                character_maximum_length=row["character_maximum_length"],
            )
        )
    return columns


def _load_enum_values(cur, udt_name: str) -> list[str] | None:
    cur.execute(
        "SELECT e.enumlabel FROM pg_type t "
        "JOIN pg_enum e ON t.oid = e.enumtypid "
        "WHERE t.typname = %s ORDER BY e.enumsortorder",
        (udt_name,),
    )
    values = [row["enumlabel"] for row in cur.fetchall()]
    return values or None


def _load_primary_key(cur, schema: str, name: str) -> list[str]:
    cur.execute(
        "SELECT kcu.column_name FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
        "WHERE tc.table_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY' "
        "ORDER BY kcu.ordinal_position",
        (schema, name),
    )
    return [row["column_name"] for row in cur.fetchall()]


def _load_foreign_keys(cur, schema: str, name: str) -> list[ForeignKeyInfo]:
    cur.execute(
        "SELECT kcu.column_name AS fk_column, ccu.table_name AS ref_table, "
        "       ccu.column_name AS ref_column "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
        "WHERE tc.table_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'FOREIGN KEY'",
        (schema, name),
    )
    return [
        ForeignKeyInfo(column=row["fk_column"], ref_table=row["ref_table"], ref_column=row["ref_column"])
        for row in cur.fetchall()
    ]


def _load_check_constraints(cur, schema: str, name: str) -> list[CheckConstraintInfo]:
    cur.execute(
        "SELECT cc.check_clause, ccu.column_name FROM information_schema.check_constraints cc "
        "JOIN information_schema.constraint_column_usage ccu "
        "  ON cc.constraint_name = ccu.constraint_name AND cc.constraint_schema = ccu.constraint_schema "
        "WHERE cc.constraint_schema = %s AND ccu.table_name = %s",
        (schema, name),
    )
    result = []
    for row in cur.fetchall():
        clause = row["check_clause"]
        if _NOT_NULL_CLAUSE_RE.search(clause):
            continue  # NOT NULL由来のcheck制約はis_nullableで別途表現済みなので除外
        result.append(
            CheckConstraintInfo(
                column=row["column_name"],
                check_clause=clause,
                allowed_values=_extract_allowed_values(clause),
            )
        )
    return result


def _extract_allowed_values(check_clause: str) -> list[str] | None:
    """`CHECK (col IN ('a','b'))` 相当（PostgreSQL正規化後は `= ANY (ARRAY[...])` 形式）から
    許容値のリストを抜き出す。抽出できないパターン（範囲制約や複雑な式など）は None。"""
    array_match = _ARRAY_LITERALS_RE.search(check_clause)
    if not array_match:
        return None
    literals = [m.replace("''", "'") for m in _STRING_LITERAL_RE.findall(array_match.group(1))]
    return literals or None


def topological_order(tables: dict[str, TableInfo]) -> tuple[list[str], list[str]]:
    """FK制約を満たすINSERT順序（親→子）を返す。

    戻り値: (順序が確定したテーブル名のリスト, 循環参照のため順序を確定できなかったテーブル名のリスト)
    自己参照FK（同じテーブル内で完結）は循環とみなさない。
    """
    deps: dict[str, set[str]] = {}
    for name, info in tables.items():
        deps[name] = {fk.ref_table for fk in info.foreign_keys if fk.ref_table != name and fk.ref_table in tables}

    ordered: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not d)
        if not ready:
            break  # 残り全部が循環参照に巻き込まれている
        for n in ready:
            ordered.append(n)
            del remaining[n]
        for d in remaining.values():
            d.difference_update(ready)

    unresolved = sorted(remaining.keys())
    return ordered, unresolved
