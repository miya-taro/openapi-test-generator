import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from request_builder import build_url, build_request_body
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


# --- テスト対象外の path param のベースライン自動生成 ---
# body/query フィールドをテストする際、そのエンドポイントの path param
# （テスト対象ではない）が未置換のまま "{userId}" のようにURLへ残ってしまう
# バグの回帰テスト。放置すると多くのサーバー実装で404/422等になり、本来
# テストしたいフィールドの検証にならない。

_PATH_PARAM_OPENAPI = {
    "paths": {
        "/users/{userId}": {
            "put": {
                "operationId": "updateUser",
                "parameters": [
                    {"name": "userId", "in": "path", "required": True, "schema": {"type": "integer", "minimum": 5}}
                ],
            }
        }
    }
}


def test_body_field_test_fills_untested_path_param_with_schema_baseline():
    case = make_case(
        path="/users/{userId}", operation_id="updateUser", method="PUT",
        param_in="body", param_name="name", input_value="Alice",
    )
    url = build_url("http://localhost:8080", case, _PATH_PARAM_OPENAPI)
    assert url == "http://localhost:8080/users/5"


def test_query_field_test_fills_untested_path_param_with_schema_baseline():
    case = make_case(
        path="/users/{userId}", operation_id="updateUser", method="PUT",
        param_in="query", param_name="page", input_value="1",
    )
    url = build_url("http://localhost:8080", case, _PATH_PARAM_OPENAPI)
    assert url.startswith("http://localhost:8080/users/5")
    assert "{userId}" not in url


def test_body_field_test_fills_untested_path_param_with_generic_default_without_openapi():
    case = make_case(
        path="/users/{userId}", operation_id="updateUser", method="PUT",
        param_in="body", param_name="name", input_value="Alice",
    )
    url = build_url("http://localhost:8080", case)
    assert url == "http://localhost:8080/users/1"


_MULTI_PATH_PARAM_OPENAPI = {
    "paths": {
        "/users/{userId}/posts/{postId}": {
            "get": {
                "operationId": "getUserPost",
                "parameters": [
                    {"name": "userId", "in": "path", "required": True, "schema": {"type": "integer", "minimum": 5}},
                    {"name": "postId", "in": "path", "required": True, "schema": {"type": "integer", "minimum": 10}},
                ],
            }
        }
    }
}


def test_multiple_path_params_only_tested_one_uses_input_value():
    # 複数 path param を持つエンドポイントで postId をテストする場合、
    # テスト対象外の userId にもスキーマベースのベースライン値が必要
    case = make_case(
        path="/users/{userId}/posts/{postId}", operation_id="getUserPost", method="GET",
        param_in="path", param_name="postId", input_value="999",
    )
    url = build_url("http://localhost:8080", case, _MULTI_PATH_PARAM_OPENAPI)
    assert url == "http://localhost:8080/users/5/posts/999"


def test_path_field_under_test_is_unaffected_by_baseline_fill():
    # テスト対象の path param 自身は、これまで通り case.input_value がそのまま使われる
    # （スキーマのベースライン値に上書きされない）。
    case = make_case(
        path="/users/{userId}", operation_id="updateUser", method="PUT",
        param_in="path", param_name="userId", input_value="999",
    )
    url = build_url("http://localhost:8080", case, _PATH_PARAM_OPENAPI)
    assert url == "http://localhost:8080/users/999"


# --- 配列型クエリパラメータの style/explode ---

ARRAY_QUERY_OPENAPI = {
    "paths": {
        "/users": {
            "get": {
                "operationId": "getUsers",
                "parameters": [
                    {
                        "name": "tags",
                        "in": "query",
                        "schema": {"type": "array", "items": {"type": "string"}},
                        # style/explode省略 → 既定 style: form, explode: true
                    }
                ],
            }
        }
    }
}


def test_array_query_param_default_style_uses_repeated_key():
    case = make_case(param_in="query", param_name="tags", input_value='["a", "b"]')
    url = build_url("http://localhost:8080", case, ARRAY_QUERY_OPENAPI)
    assert url == "http://localhost:8080/users?tags=a&tags=b"


def test_array_query_param_explode_false_uses_comma_separated():
    openapi = {
        "paths": {
            "/users": {
                "get": {
                    "operationId": "getUsers",
                    "parameters": [
                        {
                            "name": "tags",
                            "in": "query",
                            "schema": {"type": "array", "items": {"type": "string"}},
                            "style": "form",
                            "explode": False,
                        }
                    ],
                }
            }
        }
    }
    case = make_case(param_in="query", param_name="tags", input_value='["a", "b"]')
    url = build_url("http://localhost:8080", case, openapi)
    assert url == "http://localhost:8080/users?tags=a%2Cb"


def test_array_query_param_space_delimited():
    openapi = {
        "paths": {
            "/users": {
                "get": {
                    "operationId": "getUsers",
                    "parameters": [
                        {
                            "name": "tags",
                            "in": "query",
                            "schema": {"type": "array", "items": {"type": "string"}},
                            "style": "spaceDelimited",
                        }
                    ],
                }
            }
        }
    }
    case = make_case(param_in="query", param_name="tags", input_value='["a", "b"]')
    url = build_url("http://localhost:8080", case, openapi)
    assert "tags=a" in url and "b" in url
    assert "&tags=" not in url  # 繰り返しキーではなく1つのパラメータにまとまっている


def test_array_query_param_pipe_delimited():
    openapi = {
        "paths": {
            "/users": {
                "get": {
                    "operationId": "getUsers",
                    "parameters": [
                        {
                            "name": "tags",
                            "in": "query",
                            "schema": {"type": "array", "items": {"type": "string"}},
                            "style": "pipeDelimited",
                        }
                    ],
                }
            }
        }
    }
    case = make_case(param_in="query", param_name="tags", input_value='["a", "b"]')
    url = build_url("http://localhost:8080", case, openapi)
    assert url == "http://localhost:8080/users?tags=a%7Cb"


def test_non_array_query_param_unaffected_by_openapi_arg():
    case = make_case(param_in="query", param_name="page", input_value="2")
    url = build_url("http://localhost:8080", case, ARRAY_QUERY_OPENAPI)
    assert url == "http://localhost:8080/users?page=2"


def test_array_query_param_malformed_json_falls_back_to_raw_value():
    case = make_case(param_in="query", param_name="tags", input_value="not-json")
    url = build_url("http://localhost:8080", case, ARRAY_QUERY_OPENAPI)
    assert url == "http://localhost:8080/users?tags=not-json"


def test_array_query_param_without_openapi_falls_back_to_raw_value():
    # openapi未指定（execute()経由の旧来の呼び出し）では従来通りの挙動
    case = make_case(param_in="query", param_name="tags", input_value='["a", "b"]')
    url = build_url("http://localhost:8080", case)
    assert "tags=%5B" in url  # JSON文字列がそのままURLエンコードされる（従来通り）


# --- build_request_body tests ---

def test_non_body_returns_none():
    case = make_case(param_in="query")
    assert build_request_body(case, None) is None


def test_body_produces_json_body():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="Alice",
    )
    prepared = build_request_body(case, None)
    assert prepared.is_multipart is False
    assert prepared.json_body["name"] == "Alice"


def test_field_omit_marker_excluded():
    case = make_case(
        operation_id="createUser",
        path="/users",
        method="POST",
        param_in="body",
        param_name="name",
        input_value="（フィールドを省略）",
    )
    body = build_request_body(case, None).json_body
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
    body = build_request_body(case, None).json_body
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
    body = build_request_body(case, SAMPLE_OPENAPI).json_body
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
    body = build_request_body(case, SAMPLE_OPENAPI).json_body
    assert body["age"] == 25


# --- readOnly / default（ベースライン組み立て） ---

READONLY_DEFAULT_OPENAPI = {
    "paths": {
        "/tickets": {
            "post": {
                "operationId": "createTicket",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "title", "status"],
                                "properties": {
                                    "id": {"type": "integer", "readOnly": True},
                                    "title": {"type": "string"},
                                    "status": {"type": "string", "default": "open"},
                                },
                            }
                        }
                    }
                },
            }
        }
    }
}


def test_baseline_excludes_readonly_field_even_if_required():
    case = make_case(
        operation_id="createTicket",
        path="/tickets",
        method="POST",
        param_in="body",
        param_name="title",
        input_value="バグ報告",
    )
    body = build_request_body(case, READONLY_DEFAULT_OPENAPI).json_body
    assert "id" not in body
    assert body["title"] == "バグ報告"


def test_baseline_uses_schema_default_over_generic_dummy():
    case = make_case(
        operation_id="createTicket",
        path="/tickets",
        method="POST",
        param_in="body",
        param_name="title",
        input_value="バグ報告",
    )
    body = build_request_body(case, READONLY_DEFAULT_OPENAPI).json_body
    assert body["status"] == "open"


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
    body = build_request_body(case, openapi).json_body
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
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["customer"]["address"]["zipCode"] == "1234567"
    assert "customer.address.zipCode" not in body


def test_nested_field_omit_removes_only_that_key():
    case = _order_case(param_name="customer.address.zipCode", input_value="（フィールドを省略）")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert "zipCode" not in body["customer"]["address"]
    assert "name" in body["customer"]


def test_array_item_field_is_set_inside_array_element():
    case = _order_case(param_name="lines[].sku", input_value="ABC123")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["lines"][0]["sku"] == "ABC123"
    assert body["lines"][0]["qty"] == 1  # baseline (minimum)


def test_array_item_field_omit_removes_only_that_key():
    case = _order_case(param_name="lines[].qty", input_value="（フィールドを省略）")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert "qty" not in body["lines"][0]
    assert body["lines"][0]["sku"]


def test_root_body_empty_marker_sends_actual_empty_object():
    case = _order_case(param_name="requestBody", input_value="{}")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body == {}


def test_root_body_additional_properties_marker_adds_extra_key_to_valid_body():
    case = _order_case(
        param_name="requestBody", input_value='{ ...validBody, "__extra__": "value" }'
    )
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["__extra__"] == "value"
    assert body["amount"] == 1
    assert body["customer"]["name"]


# oneOf/anyOfバリアント網羅生成用マーカーの解決（parser.py が残す _oneOfVariants を消費する側）

ONE_OF_OPENAPI = {
    "paths": {
        "/contacts": {
            "post": {
                "operationId": "createContact",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string", "minLength": 1}},
                                "required": ["name"],
                                "_oneOfVariants": [
                                    {
                                        "type": "object",
                                        "required": ["name"],
                                        "properties": {"name": {"type": "string", "minLength": 1}},
                                    },
                                    {
                                        "type": "object",
                                        "required": ["email"],
                                        "properties": {"email": {"type": "string", "format": "email"}},
                                    },
                                ],
                            }
                        }
                    }
                },
            }
        }
    }
}


def _contact_case(**kwargs) -> RunCase:
    defaults = dict(operation_id="createContact", path="/contacts", method="POST", param_in="body")
    defaults.update(kwargs)
    return make_case(**defaults)


def test_one_of_variant_marker_builds_that_variants_baseline_body():
    case = _contact_case(param_name="requestBody", input_value="__ONE_OF_VARIANT__1")
    body = build_request_body(case, ONE_OF_OPENAPI).json_body
    assert body == {"email": "test@example.com"}


def test_one_of_variant_marker_out_of_range_falls_back_to_baseline():
    case = _contact_case(param_name="requestBody", input_value="__ONE_OF_VARIANT__99")
    body = build_request_body(case, ONE_OF_OPENAPI).json_body
    assert body == {"name": "a"}


# ネストしたbodyフィールドでのoneOfバリアント解決（バリアントごとに型が異なるケースを含む）

NESTED_ONE_OF_OPENAPI = {
    "paths": {
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["contact"],
                                "properties": {
                                    "contact": {
                                        # 代表バリアント（インデックス0）はobject。
                                        # インデックス1は全く異なる型（string）。
                                        "type": "object",
                                        "required": ["email"],
                                        "properties": {"email": {"type": "string", "format": "email"}},
                                        "_oneOfVariants": [
                                            {
                                                "type": "object",
                                                "required": ["email"],
                                                "properties": {"email": {"type": "string", "format": "email"}},
                                            },
                                            {"type": "string", "minLength": 3},
                                        ],
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


def _order_one_of_case(**kwargs) -> RunCase:
    defaults = dict(operation_id="createOrder", path="/orders", method="POST", param_in="body")
    defaults.update(kwargs)
    return make_case(**defaults)


def test_nested_field_one_of_variant_marker_builds_that_variants_value():
    case = _order_one_of_case(param_name="contact", input_value="__ONE_OF_VARIANT__1")
    body = build_request_body(case, NESTED_ONE_OF_OPENAPI).json_body
    # 代表バリアント（object）とは異なる型（string）のバリアント値が、field_schemaの
    # 型判定（_coerce_value）に引きずられず正しく文字列として設定されること
    assert body["contact"] == "aaa"


def test_nested_field_one_of_variant_marker_out_of_range_falls_back_to_coerce():
    case = _order_one_of_case(param_name="contact", input_value="__ONE_OF_VARIANT__99")
    body = build_request_body(case, NESTED_ONE_OF_OPENAPI).json_body
    # 解決できない場合は通常の _coerce_value 経路にフォールバックする
    # （field_schemaはobject型なので、文字列マーカーがそのまま raw 文字列として入る）
    assert body["contact"] == "__ONE_OF_VARIANT__99"


def test_null_marker_sends_actual_json_null_not_string():
    case = _order_case(param_name="amount", input_value="null")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["amount"] is None


def test_null_marker_on_nested_field():
    case = _order_case(param_name="customer.address.zipCode", input_value="null")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["customer"]["address"]["zipCode"] is None


# --- フィールド自体が array/object 型のケース（境界値・型不正テスト） ---
# generator（array.py の minItems/maxItems、common.py の型不正）はこの種のフィールドに
# JSON リテラル文字列を inputValue として出力するため、そのまま body に埋め込むと
# 「配列/オブジェクトのはずが JSON 文字列になる」という誤ったリクエストになってしまう。

def test_array_field_json_literal_is_parsed_not_sent_as_string():
    case = _order_case(param_name="lines", input_value='[{"sku": "abc", "qty": 1}]')
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["lines"] == [{"sku": "abc", "qty": 1}]
    assert isinstance(body["lines"], list)


def test_array_field_empty_array_literal_is_parsed():
    case = _order_case(param_name="lines", input_value="[]")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["lines"] == []


def test_array_field_type_mismatch_literal_stays_a_string():
    # common.py の型不正テスト由来: '"not-an-array"' というJSON文字列リテラル
    # → パース後は python の str "not-an-array" になる（意図通り、配列ではなく文字列を送る）
    case = _order_case(param_name="lines", input_value='"not-an-array"')
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["lines"] == "not-an-array"


def test_object_field_json_literal_is_parsed_not_sent_as_string():
    case = _order_case(param_name="customer", input_value='{"name": "a", "address": {"zipCode": "1234567"}}')
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["customer"] == {"name": "a", "address": {"zipCode": "1234567"}}


def test_array_field_malformed_json_falls_back_to_raw_string():
    # 万一パースできない文字列が来ても、例外にせず生の文字列にフォールバックする
    case = _order_case(param_name="lines", input_value="not valid json at all")
    body = build_request_body(case, NESTED_OPENAPI).json_body
    assert body["lines"] == "not valid json at all"


# --- multipart/form-data ---

MULTIPART_OPENAPI = {
    "paths": {
        "/avatars": {
            "post": {
                "operationId": "uploadAvatar",
                "requestBody": {
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file", "caption"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary"},
                                    "caption": {"type": "string", "minLength": 1},
                                },
                            }
                        }
                    }
                },
            }
        }
    }
}


def _avatar_case(**kwargs) -> RunCase:
    defaults = dict(operation_id="uploadAvatar", path="/avatars", method="POST", param_in="body")
    defaults.update(kwargs)
    return make_case(**defaults)


def test_multipart_is_flagged_and_not_json():
    case = _avatar_case(param_name="caption", input_value="hello")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    assert prepared.is_multipart is True
    assert prepared.json_body is None


def test_multipart_field_under_test_sent_as_form_field():
    case = _avatar_case(param_name="caption", input_value="hello world")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    assert prepared.multipart_fields["caption"] == (None, "hello world")


def test_multipart_file_upload_marker_sent_as_file_tuple():
    case = _avatar_case(param_name="file", input_value="（ファイルアップロード：ダミーファイル）")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    filename, content, content_type = prepared.multipart_fields["file"]
    assert filename  # ダミーファイル名が設定されている
    assert content  # ダミーのバイナリ内容が設定されている
    assert content_type


def test_multipart_baseline_fills_other_required_fields():
    # caption をテスト対象にしても、file（他のrequiredフィールド）もbaselineとして
    # ダミーファイル参照で埋まっている必要がある
    case = _avatar_case(param_name="caption", input_value="hello")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    assert "file" in prepared.multipart_fields
    assert len(prepared.multipart_fields["file"]) == 3  # (filename, content, content_type)


def test_multipart_omit_marker_removes_field():
    case = _avatar_case(param_name="caption", input_value="（省略）")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    assert "caption" not in prepared.multipart_fields


def test_multipart_empty_value_marker_sends_empty_string():
    case = _avatar_case(param_name="caption", input_value="（空文字）")
    prepared = build_request_body(case, MULTIPART_OPENAPI)
    assert prepared.multipart_fields["caption"] == (None, "")
