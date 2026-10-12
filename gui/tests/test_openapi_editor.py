import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from openapi_editor import load_operation_body_contract, save_operation_body_contract


def test_error_db_scopes_round_trip_and_validate(tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "edited.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    scopes = [{"table": "t_data", "columns": ["id", "value"], "where": {"site_id": 1}}]
    save_operation_body_contract(str(source), str(output), "createUser", True,
                                 {"type": "object"}, "201", {"type": "object"}, scopes)
    assert load_operation_body_contract(str(output), "createUser")["errorDbUnchanged"] == scopes
    assert load_operation_body_contract(str(source), "createUser")["errorDbUnchanged"] == []
    with pytest.raises(ValueError):
        save_operation_body_contract(str(source), str(output), "createUser", True,
                                     {"type": "object"}, "201", {}, [{"table": "t_data", "columns": []}])
    assert load_operation_body_contract(str(output), "createUser")["errorDbUnchanged"] == scopes


def _document():
    return {
        "openapi": "3.0.3",
        "info": {"title": "Sample", "version": "1"},
        "paths": {
            "/users": {
                "post": {
                    "operationId": "createUser",
                    "requestBody": {"$ref": "#/components/requestBodies/CreateUser"},
                    "responses": {
                        "201": {
                            "description": "Created",
                            "headers": {"X-Trace": {"schema": {"type": "string"}}},
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}},
                        },
                    },
                },
            },
        },
        "components": {
            "requestBodies": {
                "CreateUser": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CreateUser"}}},
                },
            },
            "schemas": {
                "CreateUser": {
                    "type": "object",
                    "required": ["email"],
                    "properties": {"email": {"type": "string", "format": "email"}},
                },
                "User": {"type": "object", "properties": {"id": {"type": "integer"}}},
            },
        },
    }


def test_load_operation_contract_reads_json_body_schemas_and_resolves_body_object_ref(tmp_path):
    source = tmp_path / "openapi.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")

    contract = load_operation_body_contract(str(source), "createUser")

    assert contract == {
        "operationId": "createUser",
        "requestBodyRequired": True,
        "requestBodySchema": {"$ref": "#/components/schemas/CreateUser"},
        "responseStatus": "201",
        "responseBodySchema": {"$ref": "#/components/schemas/User"},
        "responseBodyEmpty": False,
        "errorDbUnchanged": [],
    }


def test_save_operation_contract_writes_validated_copy_preserving_source_and_other_contracts(tmp_path):
    source = tmp_path / "openapi.json"
    destination = tmp_path / "openapi.ui-edited.json"
    original = _document()
    source.write_text(json.dumps(original), encoding="utf-8")

    result = save_operation_body_contract(
        str(source),
        str(destination),
        "createUser",
        False,
        {"type": "object", "properties": {"email": {"type": "string"}}},
        "201",
        {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
    )

    saved = json.loads(destination.read_text(encoding="utf-8"))
    operation = saved["paths"]["/users"]["post"]
    assert result == {
        "path": str(destination.resolve()),
        "operationId": "createUser",
        "responseStatus": "201",
    }
    assert operation["requestBody"]["required"] is False
    assert operation["requestBody"]["content"]["application/json"]["schema"]["properties"]["email"] == {
        "type": "string",
    }
    response = operation["responses"]["201"]
    assert response["headers"] == {"X-Trace": {"schema": {"type": "string"}}}
    assert response["content"]["application/json"]["schema"]["required"] == ["id"]
    assert json.loads(source.read_text(encoding="utf-8")) == original


def test_save_contract_rejects_overwriting_source(tmp_path):
    source = tmp_path / "openapi.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")

    with pytest.raises(ValueError, match="上書きできません"):
        save_operation_body_contract(
            str(source), str(source), "createUser", True, {}, "201", {},
        )


def test_blank_body_schemas_do_not_add_bodies_to_an_operation_that_has_none(tmp_path):
    source = tmp_path / "openapi.json"
    destination = tmp_path / "edited.json"
    original = {
        "openapi": "3.0.3",
        "paths": {"/health": {"get": {
            "operationId": "health",
            "responses": {"200": {"description": "OK"}},
        }}},
    }
    source.write_text(json.dumps(original), encoding="utf-8")

    save_operation_body_contract(
        str(source), str(destination), "health", False, None, "200", None,
    )

    saved = json.loads(destination.read_text(encoding="utf-8"))
    operation = saved["paths"]["/health"]["get"]
    assert "requestBody" not in operation
    assert operation["responses"] == original["paths"]["/health"]["get"]["responses"]


def test_blank_json_schema_does_not_add_json_media_type_to_multipart_request(tmp_path):
    source = tmp_path / "openapi.json"
    destination = tmp_path / "edited.json"
    multipart = {"schema": {"type": "object", "properties": {"upload": {"type": "string", "format": "binary"}}}}
    original = {
        "openapi": "3.0.3",
        "paths": {"/upload": {"post": {
            "operationId": "upload",
            "requestBody": {"required": True, "content": {"multipart/form-data": multipart}},
            "responses": {"200": {"description": "OK"}},
        }}},
    }
    source.write_text(json.dumps(original), encoding="utf-8")

    save_operation_body_contract(
        str(source), str(destination), "upload", True, None, "200", None,
    )

    operation = json.loads(destination.read_text(encoding="utf-8"))["paths"]["/upload"]["post"]
    assert operation["requestBody"]["content"] == {"multipart/form-data": multipart}


@pytest.mark.parametrize("status", ["199", "300", "default", "2x"])
def test_save_contract_rejects_non_success_response_status(tmp_path, status):
    source = tmp_path / "openapi.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")

    with pytest.raises(ValueError, match="200〜299または2XX"):
        save_operation_body_contract(
            str(source), str(tmp_path / "edited.json"), "createUser", True, {}, status, {},
        )


def test_invalid_json_schema_is_not_written(tmp_path):
    source = tmp_path / "openapi.json"
    destination = tmp_path / "edited.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")

    with pytest.raises(ValueError, match="schema"):
        save_operation_body_contract(
            str(source), str(destination), "createUser", True, {"type": "not-a-json-schema-type"},
            "201", {},
        )

    assert not destination.exists()


def test_new_editor_module_is_included_in_tauri_bundle_resources():
    config_path = Path(__file__).parents[2] / "gui-tauri" / "src-tauri" / "tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["bundle"]["resources"]["../../gui/openapi_editor.py"] == "gui/openapi_editor.py"


def test_save_comparison_rules_validates_values_and_preserves_previous_file(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    destination = tmp_path / "edited.json"
    schema = {"type": "object", "properties": {k: {"type": "integer", "minimum": 0} for k in ["start", "end"]},
              "x-otg-comparison-rules": [{"fields": ["start", "end"], "operator": "<=", "lower": 1, "upper": 2}]}
    save_operation_body_contract(str(source), str(destination), "createUser", True, schema, "201", None)
    loaded = load_operation_body_contract(str(destination), "createUser")
    assert loaded["requestBodySchema"]["x-otg-comparison-rules"] == schema["x-otg-comparison-rules"]
    previous = destination.read_bytes()
    schema["x-otg-comparison-rules"][0]["lower"] = -1
    with pytest.raises(ValueError, match="試験値"):
        save_operation_body_contract(str(source), str(destination), "createUser", True, schema, "201", None)
    assert destination.read_bytes() == previous


def test_explicit_empty_body_removes_content_preserving_headers_and_source(tmp_path):
    source = tmp_path / "api.json"
    destination = tmp_path / "edited.json"
    source.write_text(json.dumps(_document()), encoding="utf-8")
    save_operation_body_contract(str(source), str(destination), "createUser", True, None, "201", None, response_body_empty=True)
    contract = load_operation_body_contract(str(destination), "createUser")
    assert contract["responseBodyEmpty"] is True and contract["responseBodySchema"] is None
    assert load_operation_body_contract(str(source), "createUser")["responseBodyEmpty"] is False
    response = json.loads(destination.read_text())["paths"]["/users"]["post"]["responses"]["201"]
    assert "content" not in response and "headers" in response


def test_create_login_then_edit_and_append_without_losing_contract(tmp_path):
    from openapi_editor import create_operation_document
    draft = tmp_path / 'login.json'
    doc = create_operation_document('', '/v1/auth/login', 'POST', 'login', ['200', '400', '401'])
    draft.write_text(json.dumps(doc))
    request = {'type': 'object', 'required': ['username', 'password'], 'properties': {
        'username': {'type': 'string'}, 'password': {'type': 'string'}}}
    response = {'type': 'object', 'required': ['id', 'created_datetime'], 'properties': {
        'id': {'type': 'string'}, 'created_datetime': {'type': 'string', 'format': 'date-time'}}}
    saved = tmp_path / 'edited.json'
    save_operation_body_contract(str(draft), str(saved), 'login', True, request, '200', response)
    loaded = load_operation_body_contract(str(saved), 'login')
    assert loaded['requestBodySchema'] == request
    assert loaded['responseBodySchema'] == response
    added = create_operation_document(str(saved), '/v1/data', 'GET', 'getData', ['200'], False)
    assert added['paths']['/v1/auth/login'] == json.loads(saved.read_text())['paths']['/v1/auth/login']
    assert 'requestBody' not in added['paths']['/v1/data']['get']
    assert set(added['paths']['/v1/auth/login']['post']['responses']) == {'200', '400', '401'}
    with pytest.raises(ValueError, match='登録済み'):
        create_operation_document(str(saved), '/v1/auth/login', 'post', 'another', ['200'])
    with pytest.raises(ValueError, match='登録済み'):
        create_operation_document(str(saved), '/other', 'post', 'login', ['200'])


@pytest.mark.parametrize('route,method,name,statuses', [
    ('https://example.com', 'post', 'login', ['200']),
    ('/login?q=1', 'post', 'login', ['200']),
    ('/login', 'set', 'login', ['200']),
    ('/login', 'post', '', ['200']),
    ('/login', 'post', 'login', ['400']),
    ('/login', 'post', 'login', ['200', 'oops']),
])
def test_new_operation_invalid_inputs(route, method, name, statuses):
    from openapi_editor import create_operation_document
    with pytest.raises(ValueError):
        create_operation_document('', route, method, name, statuses)
