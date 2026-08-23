import sys
import json
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from request_builder import build_url, build_body_args
from models import RunCase


def make_case(**kwargs) -> RunCase:
    defaults = dict(
        id="TC-001-001",
        operation_id="getUsers",
        path="/users",
        method="GET",
        param_in="query",
        param_name="page",
        input_value="1",
        expected_status="200",
        expected_response_body="",
        expected_response_header="",
        expected_response_time="3秒以内",
        expected_result="",
    )
    defaults.update(kwargs)
    return RunCase(**defaults)


# --- build_url tests ---

def test_query_param_appended():
    case = make_case(param_in="query", param_name="page", input_value="2")
    url = build_url("http://localhost:8080", case)
    assert url == "http://localhost:8080/users?page=2"


def test_path_param_substituted():
    case = make_case(
        path="/users/{id}",
        param_in="path",
        param_name="id",
        input_value="42",
    )
    url = build_url("http://localhost:8080", case)
    assert url == "http://localhost:8080/users/42"


def test_body_param_no_query():
    case = make_case(param_in="body", param_name="name", input_value="Alice")
    url = build_url("http://localhost:8080", case)
    assert url == "http://localhost:8080/users"


def test_query_omit_marker():
    case = make_case(param_in="query", param_name="page", input_value="（省略）")
    url = build_url("http://localhost:8080", case)
    assert "?" not in url


def test_path_omit_marker_keeps_placeholder():
    case = make_case(path="/users/{id}", param_in="path", param_name="id", input_value="（省略）")
    url = build_url("http://localhost:8080", case)
    assert "{id}" in url


def test_query_empty_value_marker_sends_empty_string():
    case = make_case(param_in="query", param_name="q", input_value="（空文字）")
    url = build_url("http://localhost:8080", case)
    assert "q=" in url
    assert url.endswith("q=")


def test_path_empty_value_marker_sends_empty_string():
    case = make_case(path="/users/{id}", param_in="path", param_name="id", input_value="（空文字）")
    url = build_url("http://localhost:8080", case)
    assert "/users/" in url


def test_base_url_trailing_slash():
    case = make_case(param_in="query", param_name="page", input_value="1")
    url = build_url("http://localhost:8080/", case)
    assert url == "http://localhost:8080/users?page=1"


# --- build_body_args tests ---

def test_non_body_returns_empty():
    case = make_case(param_in="query")
    assert build_body_args(case, None) == []


def test_body_produces_dash_d():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="Alice",
    )
    args = build_body_args(case, None)
    assert args[0] == "-d"
    body = json.loads(args[1])
    assert body["name"] == "Alice"


def test_field_omit_marker_excluded():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="（フィールドを省略）",
    )
    args = build_body_args(case, None)
    body = json.loads(args[1])
    assert "name" not in body


def test_body_empty_value_marker_sends_empty_string():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="（空文字）",
    )
    args = build_body_args(case, None)
    body = json.loads(args[1])
    assert body["name"] == ""


# --- baseline generation tests ---

SAMPLE_OPENAPI = {
    "paths": {
        "/users": {
            "post": {
                "operationId": "createUser",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name", "age", "email"],
                                "properties": {
                                    "name": {"type": "string", "minLength": 1},
                                    "age": {"type": "integer", "minimum": 0},
                                    "email": {"type": "string", "format": "email"},
                                },
                            }
                        }
                    }
                },
            }
        }
    }
}


def test_baseline_fills_other_required_fields():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="Alice",
    )
    args = build_body_args(case, SAMPLE_OPENAPI)
    body = json.loads(args[1])
    assert body["name"] == "Alice"
    assert body["age"] == 0       # minimum: 0
    assert body["email"] == "test@example.com"  # format: email


def test_baseline_does_not_override_test_field():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="age",
        input_value="25",
    )
    args = build_body_args(case, SAMPLE_OPENAPI)
    body = json.loads(args[1])
    assert body["age"] == 25


def test_baseline_minlength_string():
    openapi = {
        "paths": {
            "/items": {
                "post": {
                    "operationId": "createItem",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["code"],
                                    "properties": {
                                        "code": {"type": "string", "minLength": 5},
                                        "name": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    case = make_case(
        operation_id="createItem",
        path="/items",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="Widget",
    )
    args = build_body_args(case, openapi)
    body = json.loads(args[1])
    assert body["code"] == "aaaaa"  # minLength: 5
    assert body["name"] == "Widget"


# --- ネストしたオブジェクト・配列要素・ルートbody（object.py 由来）のテスト ---

NESTED_OPENAPI = {
    "paths": {
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["amount", "customer"],
                                "additionalProperties": False,
                                "properties": {
                                    "amount": {"type": "integer", "minimum": 1},
                                    "customer": {
                                        "type": "object",
                                        "required": ["name", "address"],
                                        "properties": {
                                            "name": {"type": "string", "minLength": 1},
                                            "address": {
                                                "type": "object",
                                                "required": ["zipCode"],
                                                "properties": {
                                                    "zipCode": {"type": "string", "minLength": 7, "maxLength": 7},
                                                },
                                            },
                                        },
                                    },
                                    "lines": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["sku", "qty"],
                                            "properties": {
                                                "sku": {"type": "string", "minLength": 3},
                                                "qty": {"type": "integer", "minimum": 1},
                                            },
                                        },
                                    },
                                },
                            }
                        }
                    }
                },
            }
        }
    }
}


def _order_case(**kwargs) -> RunCase:
    defaults = dict(
        operation_id="createOrder",
        path="/orders",
        method="POST",
        param_in="body",
    )
    defaults.update(kwargs)
    return make_case(**defaults)


def test_nested_field_is_set_at_correct_path_not_as_flat_key():
    case = _order_case(param_name="customer.address.zipCode", input_value="1234567")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["customer"]["address"]["zipCode"] == "1234567"
    assert "customer.address.zipCode" not in body


def test_nested_field_omit_removes_only_that_key():
    case = _order_case(param_name="customer.address.zipCode", input_value="（フィールドを省略）")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert "zipCode" not in body["customer"]["address"]
    assert "name" in body["customer"]


def test_array_item_field_is_set_inside_array_element():
    case = _order_case(param_name="lines[].sku", input_value="ABC123")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["lines"][0]["sku"] == "ABC123"
    assert body["lines"][0]["qty"] == 1  # baseline (minimum)


def test_array_item_field_omit_removes_only_that_key():
    case = _order_case(param_name="lines[].qty", input_value="（フィールドを省略）")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert "qty" not in body["lines"][0]
    assert body["lines"][0]["sku"]


def test_root_body_empty_marker_sends_actual_empty_object():
    case = _order_case(param_name="requestBody", input_value="{}")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body == {}


def test_root_body_additional_properties_marker_adds_extra_key_to_valid_body():
    case = _order_case(
        param_name="requestBody", input_value='{ ...validBody, "__extra__": "value" }'
    )
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["__extra__"] == "value"
    assert body["amount"] == 1
    assert body["customer"]["name"]


def test_null_marker_sends_actual_json_null_not_string():
    case = _order_case(param_name="amount", input_value="null")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["amount"] is None


def test_null_marker_on_nested_field():
    case = _order_case(param_name="customer.address.zipCode", input_value="null")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["customer"]["address"]["zipCode"] is None


# --- フィールド自体が array/object 型のケース（境界値・型不正テスト） ---
# generator（array.py の minItems/maxItems、common.py の型不正）はこの種のフィールドに
# JSON リテラル文字列を inputValue として出力するため、そのまま body に埋め込むと
# 「配列/オブジェクトのはずが JSON 文字列になる」という誤ったリクエストになってしまう。

def test_array_field_json_literal_is_parsed_not_sent_as_string():
    case = _order_case(param_name="lines", input_value='[{"sku": "abc", "qty": 1}]')
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["lines"] == [{"sku": "abc", "qty": 1}]
    assert isinstance(body["lines"], list)


def test_array_field_empty_array_literal_is_parsed():
    case = _order_case(param_name="lines", input_value="[]")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["lines"] == []


def test_array_field_type_mismatch_literal_stays_a_string():
    # common.py の型不正テスト由来: '"not-an-array"' というJSON文字列リテラル
    # → パース後は python の str "not-an-array" になる（意図通り、配列ではなく文字列を送る）
    case = _order_case(param_name="lines", input_value='"not-an-array"')
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["lines"] == "not-an-array"


def test_object_field_json_literal_is_parsed_not_sent_as_string():
    case = _order_case(param_name="customer", input_value='{"name": "a", "address": {"zipCode": "1234567"}}')
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["customer"] == {"name": "a", "address": {"zipCode": "1234567"}}


def test_array_field_malformed_json_falls_back_to_raw_string():
    # 万一パースできない文字列が来ても、例外にせず生の文字列にフォールバックする
    case = _order_case(param_name="lines", input_value="not valid json at all")
    args = build_body_args(case, NESTED_OPENAPI)
    body = json.loads(args[1])
    assert body["lines"] == "not valid json at all"
