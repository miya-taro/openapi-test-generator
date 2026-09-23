import json
import sys
from pathlib import Path

import pytest
import jsonschema
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
import generate_mapping as mapping_module
from db_introspect import ColumnInfo, TableInfo
from generate_mapping import (
    PHPDBEvidenceError,
    _apply_php_db_evidence,
    _resource_key,
    _best_match_score,
    _build_guess,
    _collect_mutating_operations,
    _extract_body_fields,
    _guess_all,
    _normalize,
    _render_yaml,
    _score_tables,
    main as generate_mapping_main,
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


def test_build_guess_downgrades_to_medium_confidence_on_near_tie():
    # cart_itemsとorder_itemsが同一のカラム構成を持つ場合など、複数テーブルが
    # 同点で一致する状況で「高」確信度を名乗らないこと（実際にaddOrderItemで発生した回帰）。
    schema = {
        "cart_items": table("cart_items", ["product_id", "quantity", "unit_price"]),
        "order_items": table("order_items", ["product_id", "quantity", "unit_price"]),
    }
    scored = _score_tables(["productId", "quantity", "unitPrice"], schema)
    guess = _build_guess({"operationId": "addOrderItem"}, scored)
    assert guess["confidence"] == "中"
    assert "僅差" in guess["note"]


def test_build_guess_stays_high_confidence_when_runner_up_is_far_behind():
    schema = {
        "orders": table("orders", ["status", "total"]),
        "order_lines": table("order_lines", ["status"]),
    }
    scored = _score_tables(["status", "total"], schema)
    guess = _build_guess({"operationId": "createOrder"}, scored)
    assert guess["confidence"] == "高"


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


def test_render_yaml_quotes_operation_ids_that_could_break_yaml_structure():
    body = _render_yaml([{
        "operationId": "createMember\n  engine: influxdb",
        "table": "members", "confidence": "中", "note": "source", "runner_up": None,
    }])

    assert '"createMember\\n  engine: influxdb":' in body
    assert "\n  engine: influxdb:\n" not in body
    parsed = yaml.safe_load(body)
    assert list(parsed["operations"]) == ["createMember\n  engine: influxdb"]


def test_php_db_evidence_overrides_name_guess_only_after_schema_match():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": ["fullName"]}]
    guesses = [{
        "operationId": "createMember", "table": "accounts", "confidence": "低",
        "note": "名前推定", "runner_up": None,
    }]
    schema = {
        "accounts": table("accounts", ["id", "display_name"]),
        "members": table("members", ["id", "full_name"]),
    }
    evidence = {
        "format": "api-tester.php-db-evidence",
        "schemaVersion": 1,
        "operations": {
            "createMember": {
                "tables": [{
                    "table": "members", "action": "insert", "columns": ["full_name"],
                    "evidence": [{"file": "api/members.php", "line": 42}],
                }],
            },
        },
    }

    result = _apply_php_db_evidence(guesses, evidence, operations, schema)

    assert result[0]["table"] == "members"
    assert result[0]["confidence"] == "中"  # Copilot候補は一致しても自動承認しない
    assert "api/members.php:42" in result[0]["note"]
    assert "DBスキーマと一致" in result[0]["note"]


def test_php_db_evidence_with_unknown_column_becomes_unresolved():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": ["fullName"]}]
    guesses = [{
        "operationId": "createMember", "table": "accounts", "confidence": "高",
        "note": "名前推定", "runner_up": None,
    }]
    schema = {"members": table("members", ["id", "full_name"])}
    evidence = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"createMember": {"tables": [{
            "table": "members", "action": "insert", "columns": ["full_nam"],
            "evidence": [{"file": "api/members.php", "line": 42}],
        }]}},
    }

    result = _apply_php_db_evidence(guesses, evidence, operations, schema)

    assert result[0]["table"] is None
    assert result[0]["confidence"] == "低"
    assert "DBスキーマにありません" in result[0]["note"]


def test_php_db_evidence_for_unknown_table_keeps_php_source_reference():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": []}]
    guesses = [{
        "operationId": "createMember", "table": None, "confidence": "低",
        "note": "名前推定なし", "runner_up": None,
    }]
    evidence = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"createMember": {"tables": [{
            "table": "missing_table", "action": "insert", "columns": ["name"],
            "evidence": [{"file": "api/members.php", "line": 42}],
        }]}},
    }

    result = _apply_php_db_evidence(guesses, evidence, operations, {})

    assert "api/members.php:42" in result[0]["note"]
    assert "DBスキーマにありません" in result[0]["note"]


def test_php_db_evidence_does_not_choose_between_multiple_tables():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": ["fullName"]}]
    guesses = [{
        "operationId": "createMember", "table": "members", "confidence": "高",
        "note": "名前推定", "runner_up": None,
    }]
    schema = {
        "members": table("members", ["full_name"]),
        "member_profiles": table("member_profiles", ["full_name"]),
    }
    evidence = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"createMember": {"tables": [
            {"table": "members", "action": "insert", "columns": ["full_name"],
             "evidence": [{"file": "api/members.php", "line": 42}]},
            {"table": "member_profiles", "action": "insert", "columns": ["full_name"],
             "evidence": [{"file": "api/members.php", "line": 51}]},
        ]}},
    }

    result = _apply_php_db_evidence(guesses, evidence, operations, schema)

    assert result[0]["table"] is None
    assert result[0]["confidence"] == "低"
    assert "複数テーブル" in result[0]["note"]
    assert "api/members.php:42" in result[0]["runner_up"]


def test_php_db_evidence_rejects_unknown_operation_and_unsafe_source_path():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": []}]
    unknown_operation = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"missingOperation": {"tables": []}},
    }
    with pytest.raises(PHPDBEvidenceError, match="OpenAPI"):
        _apply_php_db_evidence([], unknown_operation, operations, {})

    unsafe_path = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"createMember": {"tables": [{
            "table": "members", "action": "insert", "columns": ["id"],
            "evidence": [{"file": "../outside.php", "line": 1}],
        }]}},
    }
    with pytest.raises(PHPDBEvidenceError, match="相対パス"):
        _apply_php_db_evidence([], unsafe_path, operations, {"members": table("members", ["id"])})


def test_php_db_evidence_rejects_malformed_action_and_unsafe_db_identifier():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": []}]
    for table_name, action in [("members\n  engine: influxdb", "insert"), ("members", [])]:
        evidence = {
            "format": "api-tester.php-db-evidence", "schemaVersion": 1,
            "operations": {"createMember": {"tables": [{
                "table": table_name, "action": action, "columns": ["id"],
                "evidence": [{"file": "api/members.php", "line": 1}],
            }]}},
        }
        with pytest.raises(PHPDBEvidenceError):
            _apply_php_db_evidence([], evidence, operations, {"members": table("members", ["id"])})


def test_php_db_evidence_rejects_extra_keys_and_boolean_schema_version():
    operations = [{"operationId": "createMember", "method": "post", "path": "/members", "fields": []}]
    evidence = {
        "format": "api-tester.php-db-evidence", "schemaVersion": 1, "unexpected": "ignored?",
        "operations": {},
    }
    with pytest.raises(PHPDBEvidenceError, match="未対応"):
        _apply_php_db_evidence([], evidence, operations, {})

    evidence.pop("unexpected")
    evidence["schemaVersion"] = True
    with pytest.raises(PHPDBEvidenceError, match="schemaVersion"):
        _apply_php_db_evidence([], evidence, operations, {})


def test_php_db_evidence_schema_accepts_the_documented_candidate_shape():
    repo_root = Path(__file__).resolve().parents[2]
    schema = json.loads((repo_root / "docs/php-db-evidence.schema.json").read_text(encoding="utf-8"))
    candidate = {
        "format": "api-tester.php-db-evidence",
        "schemaVersion": 1,
        "operations": {"createMember": {"tables": [{
            "table": "members", "action": "insert", "columns": ["full_name"],
            "evidence": [{"file": "api/members.php", "line": 42}],
        }]}},
    }

    jsonschema.validate(candidate, schema)


def test_main_accepts_php_db_evidence_and_writes_reviewable_mapping(tmp_path, monkeypatch):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "Test", "version": "1"},
        "paths": {"/members": {"post": {
            "operationId": "createMember",
            "requestBody": {"content": {"application/json": {"schema": {
                "type": "object", "properties": {"displayName": {"type": "string"}},
            }}}},
        }}},
    }), encoding="utf-8")
    evidence_path = tmp_path / "openapi.db-evidence.json"
    evidence_path.write_text(json.dumps({
        "format": "api-tester.php-db-evidence", "schemaVersion": 1,
        "operations": {"createMember": {"tables": [{
            "table": "members", "action": "insert", "columns": ["full_name"],
            "evidence": [{"file": "api/members.php", "line": 42}],
        }]}},
    }), encoding="utf-8")
    output = tmp_path / "mapping.generated.yaml"
    monkeypatch.setattr(mapping_module, "load_config", lambda _path: {})
    monkeypatch.setattr(mapping_module, "get_postgres_config", lambda _config: {})
    monkeypatch.setattr(mapping_module, "introspect_schema", lambda *_args, **_kwargs: {
        "members": table("members", ["id", "full_name"]),
    })

    monkeypatch.setattr(sys, "argv", [
        "generate_mapping.py",
        str(openapi_path), "--config", str(tmp_path / "db.json"),
        "--php-db-evidence", str(evidence_path), "-o", str(output),
    ])
    code = generate_mapping_main()

    assert code == 0
    rendered = output.read_text(encoding="utf-8")
    assert "table: members" in rendered
    assert "確信度: 中" in rendered
    assert "api/members.php:42" in rendered
