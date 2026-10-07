import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from openapi_editor import load_operation_body_contract, save_operation_body_contract


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
