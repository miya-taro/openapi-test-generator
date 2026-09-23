import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_backends import invariant_eval


# ---------- evaluate（安全な式評価） ----------


def test_evaluate_simple_equality_true():
    assert invariant_eval.evaluate("9 == 10 - 1") is True


def test_evaluate_simple_equality_false():
    assert invariant_eval.evaluate("9 == 10 - 2") is False


def test_evaluate_greater_equal():
    assert invariant_eval.evaluate("9 >= 0") is True
    assert invariant_eval.evaluate("-1 >= 0") is False


def test_evaluate_arithmetic_precedence():
    assert invariant_eval.evaluate("10 - 2 * 3 == 4") is True


def test_evaluate_negative_number():
    assert invariant_eval.evaluate("-5 < 0") is True


def test_evaluate_string_equality():
    assert invariant_eval.evaluate("'active' == 'active'") is True
    assert invariant_eval.evaluate("'active' == 'draft'") is False


def test_evaluate_non_comparison_expression_raises():
    # 比較式ではない（真偽値にならない）式はエラー
    with pytest.raises(invariant_eval.InvariantError, match="真偽値"):
        invariant_eval.evaluate("1 + 1")


def test_evaluate_rejects_function_call():
    with pytest.raises(invariant_eval.InvariantError):
        invariant_eval.evaluate("__import__('os').system('x') == 0")


def test_evaluate_rejects_name_reference():
    with pytest.raises(invariant_eval.InvariantError):
        invariant_eval.evaluate("os == 0")


def test_evaluate_syntax_error_raises():
    with pytest.raises(SyntaxError):
        invariant_eval.evaluate("9 ==")


def test_evaluate_type_mismatch_wrapped_as_invariant_error():
    with pytest.raises(invariant_eval.InvariantError, match="評価に失敗"):
        invariant_eval.evaluate("'a' - 1 == 0")


# ---------- substitute_db_placeholders ----------


def test_substitute_db_placeholder_with_int():
    resolved = invariant_eval.substitute_db_placeholders("{{db.stock}} == 9", {"stock": 9})
    assert resolved == "9 == 9"


def test_substitute_db_placeholder_missing_column_raises():
    with pytest.raises(invariant_eval.InvariantError, match="stock"):
        invariant_eval.substitute_db_placeholders("{{db.stock}} == 9", {"other": 1})


def test_substitute_db_placeholder_decimal_converted_to_float():
    # NUMERIC/DECIMAL列はpsycopg2からDecimalで返るが、int/floatと混在した四則演算で
    # TypeErrorにならないようfloatへ変換して埋め込む
    resolved = invariant_eval.substitute_db_placeholders("{{db.price}} - 1.5 == 8.5", {"price": Decimal("10")})
    assert resolved == "10.0 - 1.5 == 8.5"
    assert invariant_eval.evaluate(resolved) is True


def test_substitute_db_placeholder_multiple_occurrences():
    resolved = invariant_eval.substitute_db_placeholders(
        "{{db.a}} + {{db.b}} == {{db.total}}", {"a": 2, "b": 3, "total": 5}
    )
    assert invariant_eval.evaluate(resolved) is True


# ---------- literal_repr ----------


def test_literal_repr_decimal_becomes_float():
    assert invariant_eval.literal_repr(Decimal("19.99")) == "19.99"


def test_literal_repr_int_unchanged():
    assert invariant_eval.literal_repr(10) == "10"


def test_literal_repr_string_is_quoted():
    assert invariant_eval.literal_repr("active") == "'active'"
