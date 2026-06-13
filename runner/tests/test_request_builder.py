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
