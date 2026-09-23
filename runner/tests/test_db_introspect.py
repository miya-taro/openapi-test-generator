import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_introspect import (
    ForeignKeyInfo,
    TableInfo,
    _extract_allowed_values,
    topological_order,
)


def make_table(name: str, fk_targets: list[str] = None) -> TableInfo:
    fks = [ForeignKeyInfo(column=f"{t}_id", ref_table=t, ref_column="id") for t in (fk_targets or [])]
    return TableInfo(name=name, foreign_keys=fks)


# --- topological_order ---


def test_topological_order_orders_parent_before_child():
    tables = {
        "users": make_table("users"),
        "orders": make_table("orders", fk_targets=["users"]),
    }
    ordered, unresolved = topological_order(tables)
    assert ordered.index("users") < ordered.index("orders")
    assert unresolved == []


def test_topological_order_three_level_chain():
    tables = {
        "order_lines": make_table("order_lines", fk_targets=["orders"]),
        "orders": make_table("orders", fk_targets=["users"]),
        "users": make_table("users"),
    }
    ordered, unresolved = topological_order(tables)
    assert ordered.index("users") < ordered.index("orders") < ordered.index("order_lines")
    assert unresolved == []


def test_topological_order_self_reference_is_not_a_cycle():
    tables = {"employees": make_table("employees", fk_targets=["employees"])}
    ordered, unresolved = topological_order(tables)
    assert ordered == ["employees"]
    assert unresolved == []


def test_topological_order_detects_circular_reference():
    tables = {
        "a": make_table("a", fk_targets=["b"]),
        "b": make_table("b", fk_targets=["a"]),
    }
    ordered, unresolved = topological_order(tables)
    assert ordered == []
    assert unresolved == ["a", "b"]


def test_topological_order_independent_tables_are_alphabetical():
    tables = {"zebra": make_table("zebra"), "apple": make_table("apple")}
    ordered, unresolved = topological_order(tables)
    assert ordered == ["apple", "zebra"]


def test_topological_order_fk_to_table_outside_scope_ignored():
    tables = {"orders": make_table("orders", fk_targets=["users"])}  # usersは無い
    ordered, unresolved = topological_order(tables)
    assert ordered == ["orders"]
    assert unresolved == []


# --- _extract_allowed_values ---


def test_extract_allowed_values_from_any_array_pattern():
    clause = "((status)::text = ANY ((ARRAY['pending'::character varying, 'shipped'::character varying])::text[]))"
    assert _extract_allowed_values(clause) == ["pending", "shipped"]


def test_extract_allowed_values_returns_none_for_range_check():
    clause = "(price >= (0)::numeric)"
    assert _extract_allowed_values(clause) is None


def test_extract_allowed_values_returns_none_when_no_literals_in_array():
    clause = "((x)::text = ANY ((ARRAY[])::text[]))"
    assert _extract_allowed_values(clause) is None


def test_extract_allowed_values_unescapes_doubled_single_quote():
    # PostgreSQLのSQL標準文字列リテラルは埋め込まれた ' を \' ではなく '' (二重化)で
    # エスケープする。バックスラッシュエスケープ前提のパターンだと、二重化された ' を
    # 別々の文字列境界と誤認し、1個の値が2個の断片に壊れて分割されてしまっていた。
    clause = (
        "(status = ANY ((ARRAY['active'::character varying, "
        "'it''s-a-status'::character varying])::text[]))"
    )
    assert _extract_allowed_values(clause) == ["active", "it's-a-status"]
