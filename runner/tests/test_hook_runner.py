import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from hook_runner import run_hook, _split_statements

FIXTURES = Path(__file__).parent / "fixtures"
SETUP_SQL = FIXTURES / "setup.sql"
TEARDOWN_SQL = FIXTURES / "teardown.sql"

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "testdb",
    "user": "testuser",
    "password": "testpass",
}


def make_mock_conn():
    """psycopg2.connect() が返す connection のモック。"""
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur

    return mock_conn, mock_cur


# ---------- _split_statements ----------

def test_split_single_statement():
    stmts = _split_statements("SELECT 1")
    assert stmts == ["SELECT 1"]


def test_split_multiple_statements():
    sql = "SELECT 1;\nSELECT 2;\nSELECT 3"
    stmts = _split_statements(sql)
    assert len(stmts) == 3


def test_split_ignores_comment_only_blocks():
    sql = "-- comment\n;\nSELECT 1"
    stmts = _split_statements(sql)
    assert stmts == ["SELECT 1"]


def test_split_ignores_empty_segments():
    sql = "SELECT 1;;"
    stmts = _split_statements(sql)
    assert stmts == ["SELECT 1"]


# ---------- 正常系（setup） ----------

def test_setup_executes_sql_and_commits(tmp_path):
    sql_file = tmp_path / "setup.sql"
    sql_file.write_text("INSERT INTO t VALUES (1)", encoding="utf-8")

    mock_conn, mock_cur = make_mock_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        run_hook(str(sql_file), DB_CONFIG, is_teardown=False)

    mock_cur.execute.assert_called_once_with("INSERT INTO t VALUES (1)")
    mock_conn.close.assert_called_once()


def test_setup_executes_fixture_sql():
    mock_conn, mock_cur = make_mock_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        run_hook(str(SETUP_SQL), DB_CONFIG, is_teardown=False)

    assert mock_cur.execute.call_count == 2  # TRUNCATE + INSERT


def test_setup_multiple_statements_in_order(tmp_path):
    sql_file = tmp_path / "multi.sql"
    sql_file.write_text("DELETE FROM a;\nINSERT INTO a VALUES (1)", encoding="utf-8")

    mock_conn, mock_cur = make_mock_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        run_hook(str(sql_file), DB_CONFIG, is_teardown=False)

    calls = [c.args[0] for c in mock_cur.execute.call_args_list]
    assert calls[0] == "DELETE FROM a"
    assert calls[1] == "INSERT INTO a VALUES (1)"


# ---------- 異常系（setup）: 接続失敗 ----------

def test_setup_connection_failure_raises_system_exit(tmp_path):
    sql_file = tmp_path / "s.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    with patch("psycopg2.connect", side_effect=Exception("connection refused")):
        with pytest.raises(SystemExit) as exc:
            run_hook(str(sql_file), DB_CONFIG, is_teardown=False)
    assert exc.value.code == 3


# ---------- 異常系（setup）: SQL エラー ----------

def test_setup_sql_error_raises_system_exit(tmp_path):
    sql_file = tmp_path / "s.sql"
    sql_file.write_text("INVALID SQL", encoding="utf-8")

    mock_conn, mock_cur = make_mock_conn()
    mock_cur.execute.side_effect = Exception("syntax error")

    with patch("psycopg2.connect", return_value=mock_conn):
        with pytest.raises(SystemExit) as exc:
            run_hook(str(sql_file), DB_CONFIG, is_teardown=False)
    assert exc.value.code == 3


# ---------- 異常系（setup）: ファイルなし ----------

def test_setup_missing_file_raises_system_exit(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_hook(str(tmp_path / "nonexistent.sql"), DB_CONFIG, is_teardown=False)
    assert exc.value.code == 3


# ---------- 正常系（teardown）: SQL エラーでも続行 ----------

def test_teardown_sql_error_continues(tmp_path):
    sql_file = tmp_path / "t.sql"
    sql_file.write_text("BAD SQL", encoding="utf-8")

    mock_conn, mock_cur = make_mock_conn()
    mock_cur.execute.side_effect = Exception("error")

    with patch("psycopg2.connect", return_value=mock_conn):
        run_hook(str(sql_file), DB_CONFIG, is_teardown=True)
        # should not raise


def test_teardown_connection_failure_continues(tmp_path):
    sql_file = tmp_path / "t.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    with patch("psycopg2.connect", side_effect=Exception("refused")):
        run_hook(str(sql_file), DB_CONFIG, is_teardown=True)
        # should not raise


def test_teardown_missing_file_continues(tmp_path):
    run_hook(str(tmp_path / "nonexistent.sql"), DB_CONFIG, is_teardown=True)
    # should not raise


def test_teardown_executes_fixture_sql():
    mock_conn, mock_cur = make_mock_conn()
    with patch("psycopg2.connect", return_value=mock_conn):
        run_hook(str(TEARDOWN_SQL), DB_CONFIG, is_teardown=True)

    assert mock_cur.execute.call_count == 1  # TRUNCATE のみ
