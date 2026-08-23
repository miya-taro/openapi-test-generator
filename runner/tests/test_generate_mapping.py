import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_introspect import ColumnInfo, TableInfo
from generate_mapping import (
    _resource_key,
    _best_match_score,
    _build_guess,
    _collect_mutating_operations,
    _extract_body_fields,
    _guess_all,
    _normalize,
    _render_yaml,
    _score_tables,
)


def col(name) -> ColumnInfo:
    return ColumnInfo(name=name, data_type="text", udt_name="text", is_nullable=True, column_default=None)


def table(name, columns) -> TableInfo:
    return TableInfo(name=name, columns=[col(c) for c in columns])


# --- _normalize / _best_match_score ---


def test_normalize_strips_underscores_and_lowercases():
    assert _normalize("user_name") == _normalize("userName") == "username"


def test_best_match_exact_after_normalization():
    score, is_exact = _best_match_score("userName", ["user_name", "email"])
    assert score == 1.0
    assert is_exact is True


def test_best_match_fuzzy_below_threshold_scores_zero():
    score, is_exact = _best_match_score("completely_unrelated", ["id", "email"])
    assert score == 0.0
    assert is_exact is False


def test_best_match_fuzzy_above_threshold():
    score, is_exact = _best_match_score("emial", ["email"])  # typo-ish, high similarity
    assert score > 0
    assert is_exact is False


# --- _score_tables / _build_guess ---


def test_score_tables_prefers_more_matching_columns():
    schema = {
        "users": table("users", ["id", "name", "email"]),
        "orders": table("orders", ["id", "user_id", "status"]),
    }
    scored = _score_tables(["name", "email"], schema)
    assert scored[0].table == "users"


def test_build_guess_high_confidence_when_all_fields_match():
    schema = {"users": table("users", ["name", "email"])}
    scored = _score_tables(["name", "email"], schema)
    guess = _build_guess({"operationId": "createUser"}, scored)
    assert guess["table"] == "users"
    assert guess["confidence"] == "高"


def test_build_guess_low_confidence_when_no_table_matches():
    schema = {"orders": table("orders", ["id", "status"])}
    scored = _score_tables(["completely_unrelated_field"], schema)
    guess = _build_guess({"operationId": "createOrder"}, scored)
    assert guess["table"] is None
    assert guess["confidence"] == "低"


def test_build_guess_includes_runner_up_when_present():
    schema = {
        "orders": table("orders", ["status", "total"]),
        "order_lines": table("order_lines", ["status"]),
    }
    scored = _score_tables(["status", "total"], schema)
    guess = _build_guess({"operationId": "createOrder"}, scored)
    assert guess["runner_up"] is not None
    assert "order_lines" in guess["runner_up"]


# --- _resource_key ---


def test_resource_key_item_route_matches_collection_route():
    assert _resource_key("/orders/{id}") == _resource_key("/orders") == "orders"


def test_resource_key_nested_resource_is_distinguished_from_parent():
    # /orders/{id}/lines はordersではなくlinesという別リソースの操作
    assert _resource_key("/orders/{id}/lines") == "lines"
    assert _resource_key("/orders/{id}/lines") != _resource_key("/orders/{id}")


def test_resource_key_nested_item_route_matches_nested_collection_route():
    assert _resource_key("/orders/{id}/lines") == _resource_key("/orders/{id}/lines/{lineId}") == "lines"


# --- _guess_all: DELETE (no body) inherits from sibling create on same path ---


def test_delete_without_body_inherits_table_from_sibling_create():
    schema = {"orders": table("orders", ["status", "total"])}
    operations = [
        {"operationId": "createOrder", "method": "post", "path": "/orders", "fields": ["status", "total"]},
        {"operationId": "deleteOrder", "method": "delete", "path": "/orders/{id}", "fields": []},
    ]
    guesses = _guess_all(operations, schema)
    delete_guess = next(g for g in guesses if g["operationId"] == "deleteOrder")
    assert delete_guess["table"] == "orders"
    assert delete_guess["confidence"] == "中"


def test_delete_without_body_and_no_sibling_is_low_confidence():
    schema = {"orders": table("orders", ["status"])}
    operations = [{"operationId": "deleteOrder", "method": "delete", "path": "/orders/{id}", "fields": []}]
    guesses = _guess_all(operations, schema)
    assert guesses[0]["table"] is None
    assert guesses[0]["confidence"] == "低"


def test_delete_without_body_inherits_from_medium_confidence_sibling():
    # createOrderが「中」確信度でも、deleteOrderへの補完は行われる
    schema = {
        "orders": table("orders", ["status", "total"]),
        "order_lines": table("order_lines", ["status"]),
    }
    operations = [
        {
            "operationId": "createOrder", "method": "post", "path": "/orders",
            "fields": ["status", "total", "completely_unmatched_field"],
        },
        {"operationId": "deleteOrder", "method": "delete", "path": "/orders/{id}", "fields": []},
    ]
    create_guess = next(g for g in _guess_all(operations, schema) if g["operationId"] == "createOrder")
    assert create_guess["confidence"] == "中"  # 前提確認
    delete_guess = next(g for g in _guess_all(operations, schema) if g["operationId"] == "deleteOrder")
    assert delete_guess["table"] == "orders"


def test_nested_resource_does_not_leak_table_guess_to_parent_resource_delete():
    """/posts/{id}/comments (comments) と /posts/{id} (posts) は別リソースなので、
    deletePost が createComment の推定結果を誤って引き継がないこと（実際に発生した回帰）。"""
    schema = {
        "posts": table("posts", ["title", "authorId"]),
        "comments": table("comments", ["body", "rating"]),
    }
    operations = [
        {"operationId": "createPost", "method": "post", "path": "/posts", "fields": ["title", "authorId"]},
        {"operationId": "deletePost", "method": "delete", "path": "/posts/{postId}", "fields": []},
        {
            "operationId": "createComment", "method": "post", "path": "/posts/{postId}/comments",
            "fields": ["body", "rating"],
        },
    ]
    guesses = _guess_all(operations, schema)
    delete_guess = next(g for g in guesses if g["operationId"] == "deletePost")
    assert delete_guess["table"] == "posts"


def test_guess_all_preserves_original_operation_order():
    schema = {"users": table("users", ["name"])}
    operations = [
        {"operationId": "b_op", "method": "post", "path": "/b", "fields": []},
        {"operationId": "a_op", "method": "post", "path": "/a", "fields": ["name"]},
    ]
    guesses = _guess_all(operations, schema)
    assert [g["operationId"] for g in guesses] == ["b_op", "a_op"]


# --- _extract_body_fields / _collect_mutating_operations ---


def test_extract_body_fields_excludes_nested_object_and_array():
    op = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "properties": {
                            "name": {"type": "string"},
                            "address": {"type": "object"},
                            "tags": {"type": "array"},
                        }
                    }
                }
            }
        }
    }
    assert _extract_body_fields(op) == ["name"]


def test_extract_body_fields_empty_when_no_request_body():
    assert _extract_body_fields({}) == []


def test_collect_mutating_operations_skips_get():
    openapi = {
        "paths": {
            "/users": {
                "get": {"operationId": "listUsers"},
                "post": {"operationId": "createUser", "requestBody": {}},
            }
        }
    }
    ops = _collect_mutating_operations(openapi)
    assert [o["operationId"] for o in ops] == ["createUser"]


def test_collect_mutating_operations_skips_missing_operation_id():
    openapi = {"paths": {"/users": {"post": {}}}}
    assert _collect_mutating_operations(openapi) == []


# --- _render_yaml ---


def test_render_yaml_uses_placeholder_when_table_is_none():
    guesses = [{"operationId": "op1", "table": None, "confidence": "低", "note": "n/a", "runner_up": None}]
    body = _render_yaml(guesses)
    assert "__FILL_ME_IN__" in body


def test_render_yaml_includes_confidence_and_runner_up():
    guesses = [
        {"operationId": "createOrder", "table": "orders", "confidence": "高", "note": "一致 2/2", "runner_up": "order_lines（一致 1/2）"}
    ]
    body = _render_yaml(guesses)
    assert "table: orders" in body
    assert "確信度: 高" in body
    assert "次点候補: order_lines" in body
