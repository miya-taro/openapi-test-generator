from __future__ import annotations
import sys
from pathlib import Path

import psycopg2


def run_hook(sql_path: str, db_config: dict, is_teardown: bool = False) -> None:
    """
    sql_path:    SQL ファイルのパス
    db_config:   config.json の db セクション（psycopg2.connect に渡す）
    is_teardown: True の場合は失敗時に警告ログのみで続行する
    """
    hook_type = "teardown" if is_teardown else "setup"

    sql = _load_sql(sql_path, hook_type, is_teardown)

    try:
        conn = psycopg2.connect(**db_config)
    except Exception as e:
        msg = f"[{hook_type}] DB 接続失敗: {e}"
        if is_teardown:
            print(f"[WARN] {msg}", file=sys.stderr)
            return
        print(f"[ERROR] {msg}", file=sys.stderr)
        raise SystemExit(3) from e

    try:
        with conn:
            with conn.cursor() as cur:
                statements = _split_statements(sql)
                for stmt in statements:
                    print(f"[{hook_type}] SQL: {stmt[:60].strip()}{'...' if len(stmt) > 60 else ''}")
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        msg = f"[{hook_type}] SQL エラー: {e}"
                        if is_teardown:
                            print(f"[WARN] {msg}", file=sys.stderr)
                            conn.rollback()
                            return
                        print(f"[ERROR] {msg}", file=sys.stderr)
                        raise SystemExit(3) from e
    finally:
        conn.close()


def _load_sql(sql_path: str, hook_type: str, is_teardown: bool) -> str:
    path = Path(sql_path)
    if not path.exists():
        msg = f"[{hook_type}] SQL ファイルが見つかりません: {sql_path}"
        if is_teardown:
            print(f"[WARN] {msg}", file=sys.stderr)
            return ""
        print(f"[ERROR] {msg}", file=sys.stderr)
        raise SystemExit(3)
    return path.read_text(encoding="utf-8")


def _split_statements(sql: str) -> list[str]:
    """`;` で区切り、空・コメントのみの行を除去して返す。

    文字列リテラル（'...'）内の`;`は区切りとして扱わない
    （例: INSERT INTO notes (msg) VALUES ('hello; world') を1文として保つ）。
    素朴に sql.split(";") していると、値に`;`を含むだけの正当な1文が2つの
    構文的に壊れた断片に分割され、SQL構文エラーになっていた。
    SQLの文字列リテラルはシングルクォートの二重化(`''`)でエスケープするため、
    それも1個のリテラル`'`として扱う（区切りとして誤反応しない）。
    """
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    text = "\n".join(lines)

    stmts: list[str] = []
    current: list[str] = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    current.append("''")
                    i += 2
                    continue
                in_string = False
            current.append(ch)
            i += 1
            continue
        if ch == "'":
            in_string = True
            current.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(current).strip()
            if stmt:
                stmts.append(stmt)
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1

    stmt = "".join(current).strip()
    if stmt:
        stmts.append(stmt)
    return stmts
