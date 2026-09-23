"""db_check.invariants（不変条件）の式を安全に評価する。

「stockは注文数量ぶんだけ減っている」「stockは負にならない」のような、絶対値ではなく
関係性を検証する式を扱う。任意のPythonコードを実行できてしまう素朴な eval() は使わず、
ASTを組み立てた上で許可した演算（四則演算・比較）のノード種別のみを再帰的に評価する
ホワイトリスト方式にすることで、安全性を保つ。
"""
from __future__ import annotations
import ast
import operator
import re
from decimal import Decimal

_BINOPS: dict[type, object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_COMPARES: dict[type, object] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class InvariantError(Exception):
    pass


def literal_repr(value: object) -> str:
    """値をinvariant式に埋め込める安全なPythonリテラル表現に変換する。

    psycopg2はPostgreSQLのNUMERIC/DECIMAL列をDecimalで返すが、Decimalとint/floatの
    混在した四則演算はTypeErrorになる（例: Decimal('10') - 1.5）。invariant式は
    厳密な10進誤差より「関係性が成立しているか」を見る用途のため、Decimalはfloatに
    変換して式に埋め込む（postgres_backend._values_equalの厳密比較とは目的が異なる）。
    """
    if isinstance(value, Decimal):
        value = float(value)
    return repr(value)


def substitute_db_placeholders(expr: str, row: dict) -> str:
    """invariant式中の `{{db.<カラム名>}}` を、実際にSELECTした行の値（のPythonリテラル表現）
    に置換する。db_scenario.resolve_invariant_expr が response/given を解決済みで、
    db だけがここで残っている前提。
    """
    def _replace(m: re.Match) -> str:
        column = m.group(1)
        if column not in row:
            raise InvariantError(f"実測値に '{column}' カラムが存在しません")
        return literal_repr(row[column])

    return re.sub(r"\{\{\s*db\.([\w.]+)\s*\}\}", _replace, expr)


def evaluate(expr: str) -> bool:
    """プレースホルダ解決済みの（＝リテラル値だけになった）式を評価し、真偽値を返す。

    例: "9 == 10 - 1" -> True, "9 >= 0" -> True
    """
    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval_node(tree.body, expr)
    except (SyntaxError, InvariantError):
        raise
    except Exception as e:  # noqa: BLE001 - 演算子の型不一致(例: 文字列同士の引き算)等をまとめて包む
        raise InvariantError(f"invariant式の評価に失敗しました: {expr!r}: {e}") from e

    if not isinstance(result, bool):
        raise InvariantError(
            f"invariant式は真偽値（比較式）である必要があります: {expr!r}（結果: {result!r}）"
        )
    return result


def _eval_node(node: ast.AST, expr: str):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, expr)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval_node(node.left, expr), _eval_node(node.right, expr))
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARES:
        left = _eval_node(node.left, expr)
        right = _eval_node(node.comparators[0], expr)
        return _COMPARES[type(node.ops[0])](left, right)
    raise InvariantError(f"invariant式に使用できない構文が含まれています: {expr!r}")
