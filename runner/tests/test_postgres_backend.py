import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_backends import postgres_backend
from db_scenario import DBCheck

DB_CONFIG = {"host": "localhost", "port": 5432, "dbname": "testdb", "user": "u", "password": "p"}


def make_mock_conn(rows: list[dict]):
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = rows

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn, mock_cur


# ---------- SQL組み立て ----------


def test_check_builds_select_with_where_and_calls_connect():
    mock_conn, mock_cur = make_mock_conn([{"name": "太郎", "email": "taro@example.com"}])
    check = DBCheck(engine="postgres", table="users", where={"email": "taro@example.com"}, expect={})

    with patch("psycopg2.connect", return_value=mock_conn) as mock_connect:
        ok, detail = postgres_backend.check(check, DB_CONFIG)

    mock_connect.assert_called_once_with(**DB_CONFIG)
    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert "users" in executed_sql
    assert "email" in executed_sql
    assert executed_params == ["taro@example.com"]
    assert ok is True
    mock_conn.close.assert_called_once()


def test_check_evaluates_invariants_end_to_end():
    mock_conn, mock_cur = make_mock_conn([{"stock": 9}])
    check = DBCheck(
        engine="postgres", table="products", where={"id": 5}, expect={},
        invariants=["{{db.stock}} == 10 - 1"],
    )

    with patch("psycopg2.connect", return_value=mock_conn):
        ok, detail = postgres_backend.check(check, DB_CONFIG)

    assert ok is True, detail


def test_check_without_where_selects_all():
    mock_conn, mock_cur = make_mock_conn([{"id": 1}])
    check = DBCheck(engine="postgres", table="users", where=None, expect={})

    with patch("psycopg2.connect", return_value=mock_conn):
        postgres_backend.check(check, DB_CONFIG)

    executed_sql, executed_params = mock_cur.execute.call_args[0]
    assert "WHERE" not in executed_sql
    assert executed_params == []


def test_check_uses_raw_sql_when_given():
    mock_conn, mock_cur = make_mock_conn([{"cnt": 3}])
    check = DBCheck(engine="postgres", raw_sql="SELECT COUNT(*) AS cnt FROM users", expect={"exists": True})

    with patch("psycopg2.connect", return_value=mock_conn):
        ok, detail = postgres_backend.check(check, DB_CONFIG)

    mock_cur.execute.assert_called_once_with("SELECT COUNT(*) AS cnt FROM users")
    assert ok is True


def test_check_rejects_invalid_table_identifier():
    check = DBCheck(engine="postgres", table="users; DROP TABLE users;--", where={}, expect={})
    with pytest.raises(ValueError):
        postgres_backend._build_select(check.table, {})


def test_check_rejects_invalid_column_identifier():
    with pytest.raises(ValueError):
        postgres_backend._build_select("users", {"a; DROP TABLE users;--": "x"})


def test_matching_primary_keys_requires_single_primary_key_and_binds_match_values():
    mock_conn, mock_cur = make_mock_conn([])
    mock_cur.fetchall.side_effect = [[("id",)], [(8,), (9,)]]

    with patch("psycopg2.connect", return_value=mock_conn):
        result = postgres_backend.matching_primary_keys(
            DB_CONFIG, "users", "id", {"email": "test@example.com", "nickname": None}
        )

    assert result == [8, 9]
    assert mock_cur.execute.call_count == 2
    select_sql, select_params = mock_cur.execute.call_args[0]
    assert '"email" = %s' in select_sql
    assert '"nickname" IS NULL' in select_sql
    assert select_params == ["test@example.com"]
    mock_conn.close.assert_called_once()


def test_matching_primary_keys_rejects_composite_primary_key():
    mock_conn, mock_cur = make_mock_conn([])
    mock_cur.fetchall.return_value = [("tenant_id",), ("id",)]

    with patch("psycopg2.connect", return_value=mock_conn):
        with pytest.raises(postgres_backend.DBResponseCheckError, match="単一カラム"):
            postgres_backend.matching_primary_keys(DB_CONFIG, "users", "id", {"email": "x"})

    assert mock_cur.execute.call_count == 1
    mock_conn.close.assert_called_once()


def test_check_no_table_and_no_raw_sql_fails_gracefully():
    mock_conn, mock_cur = make_mock_conn([])
    check = DBCheck(engine="postgres", expect={})
    with patch("psycopg2.connect", return_value=mock_conn):
        ok, detail = postgres_backend.check(check, DB_CONFIG)
    assert ok is False
    assert "table" in detail or "raw_sql" in detail


# ---------- 比較ロジック ----------


def test_compare_row_exists_and_columns_match():
    ok, detail = postgres_backend._compare([{"name": "太郎", "email": "t@example.com"}], {"exists": True, "columns": {"name": "太郎"}})
    assert ok is True
    assert detail == ""


def test_compare_decimal_column_matches_equal_looking_float():
    # 回帰テスト: psycopg2はNUMERIC/DECIMAL列をDecimalで返す。Decimal("19.99") == 19.99 は
    # 素朴な比較だとFalseになる（19.99は二進浮動小数点として正確に表現できないため）。
    # 「10進数表記として同じ値」なら一致とみなす必要がある。
    from decimal import Decimal

    ok, detail = postgres_backend._compare(
        [{"price": Decimal("19.99")}], {"exists": True, "columns": {"price": 19.99}}
    )
    assert ok is True, detail


def test_compare_decimal_column_still_detects_real_mismatch():
    from decimal import Decimal

    ok, detail = postgres_backend._compare(
        [{"price": Decimal("19.99")}], {"exists": True, "columns": {"price": 20.00}}
    )
    assert ok is False
    assert "price" in detail


def test_compare_decimal_column_matches_integer_value():
    from decimal import Decimal

    ok, detail = postgres_backend._compare(
        [{"price": Decimal("100")}], {"exists": True, "columns": {"price": 100}}
    )
    assert ok is True, detail


def test_compare_row_missing_when_expected_fails():
    ok, detail = postgres_backend._compare([], {"exists": True})
    assert ok is False
    assert "見つかりません" in detail


def test_compare_row_exists_when_should_not():
    ok, detail = postgres_backend._compare([{"id": 1}], {"exists": False})
    assert ok is False
    assert "存在しないはず" in detail


def test_compare_no_rows_when_exists_false_passes():
    ok, detail = postgres_backend._compare([], {"exists": False})
    assert ok is True


def test_compare_column_value_mismatch():
    ok, detail = postgres_backend._compare([{"name": "花子"}], {"exists": True, "columns": {"name": "太郎"}})
    assert ok is False
    assert "name" in detail


def test_compare_missing_column_reported():
    ok, detail = postgres_backend._compare([{"id": 1}], {"exists": True, "columns": {"name": "太郎"}})
    assert ok is False
    assert "存在しません" in detail


def test_compare_default_expect_requires_existence():
    # expect が空の場合、デフォルトで exists=True 扱い
    ok, detail = postgres_backend._compare([], {})
    assert ok is False


# ---------- invariants（不変条件） ----------


def test_compare_invariant_pass_does_not_affect_ok():
    ok, detail = postgres_backend._compare(
        [{"stock": 9}], {"exists": True}, ["{{db.stock}} == 10 - 1"]
    )
    assert ok is True
    assert detail == ""


def test_compare_invariant_fail_reports_detail():
    ok, detail = postgres_backend._compare(
        [{"stock": 9}], {"exists": True}, ["{{db.stock}} == 10 - 2"]
    )
    assert ok is False
    assert "不変条件を満たしません" in detail


def test_compare_invariant_never_negative():
    ok, detail = postgres_backend._compare([{"stock": 0}], {"exists": True}, ["{{db.stock}} >= 0"])
    assert ok is True

    ok, detail = postgres_backend._compare([{"stock": -1}], {"exists": True}, ["{{db.stock}} >= 0"])
    assert ok is False


def test_compare_invariant_missing_column_reports_error_not_crash():
    ok, detail = postgres_backend._compare([{"other": 1}], {"exists": True}, ["{{db.stock}} >= 0"])
    assert ok is False
    assert "stock" in detail


def test_compare_invariant_combined_with_columns_both_must_pass():
    ok, detail = postgres_backend._compare(
        [{"name": "花子", "stock": 9}],
        {"exists": True, "columns": {"name": "太郎"}},  # わざと不一致
        ["{{db.stock}} >= 0"],
    )
    assert ok is False
    assert "name" in detail


def test_compare_invariant_decimal_column_does_not_raise_typeerror():
    from decimal import Decimal

    ok, detail = postgres_backend._compare(
        [{"price": Decimal("19.99")}], {"exists": True}, ["{{db.price}} - 1.99 == 18.0"]
    )
    assert ok is True, detail


def test_compare_no_invariants_arg_defaults_to_empty():
    # invariants を省略した既存の呼び出し方（後方互換）も引き続き動作する
    ok, detail = postgres_backend._compare([{"id": 1}], {"exists": True})
    assert ok is True
