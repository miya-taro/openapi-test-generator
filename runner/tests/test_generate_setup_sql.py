import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_introspect import CheckConstraintInfo, ColumnInfo, ForeignKeyInfo, TableInfo
from generate_setup_sql import (
    _build_insert,
    _build_teardown_sql,
    _placeholder_value,
    _select_columns_and_values,
    _sql_string,
)


def col(name, data_type, nullable=False, default=None, udt_name=None, enum_values=None) -> ColumnInfo:
    return ColumnInfo(
        name=name, data_type=data_type, udt_name=udt_name or data_type,
        is_nullable=nullable, column_default=default, enum_values=enum_values,
    )


# --- _select_columns_and_values ---


def test_pk_column_always_included_with_seed_value():
    table = TableInfo(name="users", columns=[col("id", "integer")], primary_key=["id"])
    columns, values, comments = _select_columns_and_values(table)
    assert columns == ["id"]
    assert values == ["1"]


def test_not_null_without_default_included():
    table = TableInfo(name="users", columns=[col("email", "character varying")])
    columns, values, _ = _select_columns_and_values(table)
    assert columns == ["email"]


def test_nullable_column_without_default_is_omitted():
    table = TableInfo(name="users", columns=[col("nickname", "character varying", nullable=True)])
    columns, _, _ = _select_columns_and_values(table)
    assert columns == []


def test_not_null_with_default_is_omitted():
    table = TableInfo(name="users", columns=[col("created_at", "timestamp without time zone", default="now()")])
    columns, _, _ = _select_columns_and_values(table)
    assert columns == []


def test_fk_column_always_included_even_if_nullable():
    table = TableInfo(
        name="orders",
        columns=[col("user_id", "integer", nullable=True)],
        foreign_keys=[ForeignKeyInfo(column="user_id", ref_table="users", ref_column="id")],
    )
    columns, values, comments = _select_columns_and_values(table)
    assert columns == ["user_id"]
    assert values == ["1"]
    assert "FK: user_id -> users.id" in comments[0]


def test_self_referential_fk_is_flagged_in_comment():
    table = TableInfo(
        name="employees",
        columns=[col("manager_id", "integer")],
        foreign_keys=[ForeignKeyInfo(column="manager_id", ref_table="employees", ref_column="id")],
    )
    _, _, comments = _select_columns_and_values(table)
    assert "自己参照" in comments[0]


# --- _placeholder_value ---


def test_placeholder_numeric():
    assert _placeholder_value(col("price", "numeric"), None) == "1"


def test_placeholder_boolean():
    assert _placeholder_value(col("active", "boolean"), None) == "true"


def test_placeholder_text_uses_column_name():
    assert _placeholder_value(col("name", "character varying"), None) == "'placeholder_name'"


def test_placeholder_escapes_single_quote_in_column_name():
    assert _sql_string("it's") == "'it''s'"


def test_placeholder_uuid():
    assert _placeholder_value(col("id", "uuid"), None) == "'00000000-0000-0000-0000-000000000001'"


def test_placeholder_jsonb():
    assert _placeholder_value(col("meta", "jsonb"), None) == "'{}'::jsonb"


def test_placeholder_array_type():
    c = col("tags", "ARRAY", udt_name="_text")
    assert _placeholder_value(c, None) == "'{}'"


def test_placeholder_enum_uses_first_value():
    c = col("status", "USER-DEFINED", enum_values=["pending", "shipped"])
    assert _placeholder_value(c, None) == "'pending'"


def test_placeholder_check_constraint_allowed_values_used_when_no_enum():
    check = CheckConstraintInfo(column="status", check_clause="...", allowed_values=["a", "b"])
    assert _placeholder_value(col("status", "character varying"), check) == "'a'"


def test_placeholder_unknown_type_falls_back_to_null():
    assert _placeholder_value(col("x", "some_exotic_type"), None) == "NULL"


# --- _build_insert (warnings for unresolved CHECK constraints) ---


def test_build_insert_warns_on_unresolved_check_constraint():
    table = TableInfo(
        name="orders",
        columns=[col("id", "integer")],
        primary_key=["id"],
        check_constraints=[CheckConstraintInfo(column="id", check_clause="(id > 0)", allowed_values=None)],
    )
    sql = _build_insert(table)
    assert "WARNING" in sql
    assert "id" in sql


def test_build_insert_no_warning_when_check_resolved():
    table = TableInfo(
        name="orders",
        columns=[col("status", "character varying")],
        check_constraints=[
            CheckConstraintInfo(column="status", check_clause="...", allowed_values=["pending"])
        ],
    )
    sql = _build_insert(table)
    assert "WARNING" not in sql
    assert "'pending'" in sql


# --- _build_teardown_sql ---


def test_teardown_sql_is_reverse_order():
    sql = _build_teardown_sql(["users", "orders", "order_lines"])
    lines = [l for l in sql.splitlines() if l.strip()]
    assert lines[0].startswith('TRUNCATE TABLE "order_lines"')
    assert lines[-1].startswith('TRUNCATE TABLE "users"')
