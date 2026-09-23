import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import db_factory
from db_introspect import CheckConstraintInfo, ColumnInfo, TableInfo

DB_CONFIG = {"host": "localhost", "port": 5432, "dbname": "testdb", "user": "u", "password": "p"}


def make_mock_conn(returned_row: dict):
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = returned_row

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


def _col(name, data_type="character varying", is_nullable=True, column_default=None,
         enum_values=None, character_maximum_length=None, udt_name="varchar"):
    return ColumnInfo(
        name=name, data_type=data_type, udt_name=udt_name, is_nullable=is_nullable,
        column_default=column_default, enum_values=enum_values,
        character_maximum_length=character_maximum_length,
    )


PRODUCTS_TABLE = TableInfo(
    name="products",
    columns=[
        _col("id", data_type="integer", is_nullable=False, column_default="nextval('products_id_seq'::regclass)", udt_name="int4"),
        _col("name", is_nullable=False),
        _col("stock", data_type="integer", is_nullable=False, udt_name="int4"),
        _col("note", is_nullable=True),  # NULL許容・デフォルト無し → 未指定なら除外
        _col("created_at", data_type="timestamp without time zone", is_nullable=False, column_default="now()"),  # デフォルトあり → 未指定なら除外
    ],
    primary_key=["id"],
)


# ---------- create() ----------


def test_create_fills_required_columns_only():
    returned_row = {"id": 1, "name": "商品A", "stock": 10, "note": None, "created_at": "2026-01-01"}
    mock_conn, mock_cur = make_mock_conn(returned_row)

    with patch.object(db_factory, "introspect_schema", return_value={"products": PRODUCTS_TABLE}):
        with patch("psycopg2.connect", return_value=mock_conn):
            row, primary_key = db_factory.create(DB_CONFIG, "products", {"name": "商品A", "stock": 10})

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert "products" in executed_sql
    assert '"name"' in executed_sql and '"stock"' in executed_sql
    assert '"note"' not in executed_sql  # nullable・未指定なので含めない
    assert '"created_at"' not in executed_sql  # デフォルトあり・未指定なので含めない
    assert '"id"' not in executed_sql  # 自動採番なので含めない
    assert executed_params == ["商品A", 10]
    assert row == returned_row
    assert primary_key == {"id": 1}


def test_create_ignores_explicit_value_for_auto_generated_column():
    mock_conn, mock_cur = make_mock_conn({"id": 1, "name": "x", "stock": 1})

    with patch.object(db_factory, "introspect_schema", return_value={"products": PRODUCTS_TABLE}):
        with patch("psycopg2.connect", return_value=mock_conn):
            db_factory.create(DB_CONFIG, "products", {"id": 999, "name": "x", "stock": 1})

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert '"id"' not in executed_sql
    assert 999 not in executed_params


def test_create_uses_enum_default_when_column_unspecified():
    table = TableInfo(
        name="users",
        columns=[
            _col("id", data_type="integer", is_nullable=False, column_default="nextval('users_id_seq')", udt_name="int4"),
            _col("role", is_nullable=False, enum_values=["member", "admin"]),
        ],
        primary_key=["id"],
    )
    mock_conn, mock_cur = make_mock_conn({"id": 1, "role": "member"})

    with patch.object(db_factory, "introspect_schema", return_value={"users": table}):
        with patch("psycopg2.connect", return_value=mock_conn):
            db_factory.create(DB_CONFIG, "users", {})

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert '"role"' in executed_sql
    assert executed_params == ["member"]


def test_create_uses_check_constraint_allowed_values():
    table = TableInfo(
        name="orders",
        columns=[
            _col("id", data_type="integer", is_nullable=False, column_default="nextval('orders_id_seq')", udt_name="int4"),
            _col("status", is_nullable=False),
        ],
        primary_key=["id"],
        check_constraints=[CheckConstraintInfo(column="status", check_clause="...", allowed_values=["pending", "shipped"])],
    )
    mock_conn, mock_cur = make_mock_conn({"id": 1, "status": "pending"})

    with patch.object(db_factory, "introspect_schema", return_value={"orders": table}):
        with patch("psycopg2.connect", return_value=mock_conn):
            db_factory.create(DB_CONFIG, "orders", {})

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert executed_params == ["pending"]


def test_create_raises_for_unknown_table():
    with patch.object(db_factory, "introspect_schema", return_value={}):
        with pytest.raises(db_factory.FactoryError, match="見つかりません"):
            db_factory.create(DB_CONFIG, "no_such_table", {})


def test_create_raises_when_type_unsupported_and_not_provided():
    table = TableInfo(
        name="things",
        columns=[_col("payload", data_type="bytea", is_nullable=False, udt_name="bytea")],
        primary_key=[],
    )
    with patch.object(db_factory, "introspect_schema", return_value={"things": table}):
        with pytest.raises(db_factory.FactoryError, match="payload"):
            db_factory.create(DB_CONFIG, "things", {})


def test_create_wraps_psycopg2_error_as_factory_error():
    import psycopg2

    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.execute.side_effect = psycopg2.IntegrityError("duplicate key")
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch.object(db_factory, "introspect_schema", return_value={"products": PRODUCTS_TABLE}):
        with patch("psycopg2.connect", return_value=mock_conn):
            with pytest.raises(db_factory.FactoryError, match="products"):
                db_factory.create(DB_CONFIG, "products", {"name": "x", "stock": 1})
    mock_conn.rollback.assert_called_once()


def test_create_no_insertable_columns_raises():
    table = TableInfo(name="empty_ish", columns=[], primary_key=[])
    with patch.object(db_factory, "introspect_schema", return_value={"empty_ish": table}):
        with pytest.raises(db_factory.FactoryError, match="empty_ish"):
            db_factory.create(DB_CONFIG, "empty_ish", {})


# ---------- delete() ----------


def test_delete_builds_correct_where_and_params():
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    with patch("psycopg2.connect", return_value=mock_conn):
        db_factory.delete(DB_CONFIG, "products", {"id": 5})

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert "products" in executed_sql
    assert '"id" = %s' in executed_sql
    assert executed_params == [5]
    mock_conn.commit.assert_called_once()


def test_delete_noop_when_primary_key_empty():
    with patch("psycopg2.connect") as mock_connect:
        db_factory.delete(DB_CONFIG, "products", {})
    mock_connect.assert_not_called()


# ---------- 識別子検証 ----------


def test_quote_ident_rejects_invalid_identifier():
    with pytest.raises(db_factory.FactoryError):
        db_factory._quote_ident("products; DROP TABLE products;--")


def test_quote_ident_accepts_valid_identifier():
    assert db_factory._quote_ident("products") == '"products"'
