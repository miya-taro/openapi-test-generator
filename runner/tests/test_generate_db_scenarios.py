import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import generate_db_scenarios as gen_module
from db_scenario import load_scenarios

SAMPLE_OPENAPI = {
    "openapi": "3.1.0",
    "paths": {
        "/pets": {
            "post": {
                "operationId": "createPet",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "integer"},
                                    "name": {"type": "string", "minLength": 1},
                                    "category": {
                                        "type": "object",
                                        "properties": {"id": {"type": "integer"}},
                                    },
                                    "status": {"type": "string", "enum": ["available", "sold"]},
                                },
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
        "/pets/{petId}": {
            "put": {
                "operationId": "updatePet",
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                        }
                    }
                },
                "responses": {"200": {"description": "OK"}},
            },
            "delete": {
                "operationId": "deletePet",
                "parameters": [{"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "OK"}},
            },
            "get": {"operationId": "getPet", "responses": {"200": {"description": "OK"}}},
        },
    },
}


def test_generates_one_scenario_per_mapped_operation():
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert len(scenarios) == 1
    assert scenarios[0]["request"]["operationId"] == "createPet"


def test_get_operations_are_never_included():
    mapping = {"operations": {"getPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert scenarios == []


def test_unmapped_operations_are_skipped():
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert all(s["request"]["operationId"] == "createPet" for s in scenarios)


def test_create_body_fills_all_properties_even_without_required():
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    body = scenarios[0]["request"]["body"]
    assert "name" in body
    assert "status" in body
    assert body["status"] == "available"  # enumの先頭値
    assert "category" in body  # ネストしたオブジェクトも埋まる


def test_where_excludes_id_and_nested_fields():
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    where = scenarios[0]["db_check"]["where"]
    assert "id" not in where
    assert "category" not in where
    assert where["name"]
    assert where["status"] == "available"


def test_delete_scenario_expects_not_exists_and_uses_response_id_placeholder():
    mapping = {"operations": {"deletePet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    s = scenarios[0]
    assert s["db_check"]["expect"]["exists"] is False
    assert s["request"]["path_params"]["petId"] == "{{response.id}}"


def test_update_scenario_path_param_uses_response_id_placeholder():
    mapping = {"operations": {"updatePet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert scenarios[0]["request"]["path_params"]["petId"] == "{{response.id}}"


def test_missing_table_mapping_uses_placeholder():
    mapping = {"operations": {"createPet": {"engine": "postgres"}}}  # table 未指定
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert scenarios[0]["db_check"]["table"] == gen_module._PLACEHOLDER


def test_influxdb_engine_splits_tags_and_fields():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/sensor": {
                "post": {
                    "operationId": "postSensor",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "device_id": {"type": "string", "minLength": 1},
                                        "temperature": {"type": "number"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        },
    }
    mapping = {"postSensor": {"engine": "influxdb", "measurement": "sensor_data", "tags": ["device_id"]}}
    scenarios = gen_module._generate_scenarios(api, mapping)
    check = scenarios[0]["db_check"]
    assert check["engine"] == "influxdb"
    assert "device_id" in check["tags"]
    assert "temperature" in check["expect"]["fields"]
    assert "device_id" not in check["expect"]["fields"]


def test_generated_yaml_is_loadable_by_db_scenario_module(tmp_path):
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    out_path = tmp_path / "generated.yaml"
    out_path.write_text(
        gen_module._HEADER_COMMENT
        + yaml.dump({"scenarios": scenarios}, allow_unicode=True, sort_keys=False, Dumper=gen_module._NoAliasDumper),
        encoding="utf-8",
    )

    loaded = load_scenarios(out_path)
    assert len(loaded) == 1
    assert loaded[0].request.operation_id == "createPet"


def test_generated_yaml_has_no_anchor_syntax(tmp_path):
    # 同じ辞書オブジェクトを body/where/columns で使い回しても &id001/*id001 のような
    # YAMLアンカー記法にならないことを確認する（人間が読む前提の叩き台のため）
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    text = yaml.dump({"scenarios": scenarios}, allow_unicode=True, sort_keys=False, Dumper=gen_module._NoAliasDumper)
    assert "&id" not in text
    assert "*id" not in text


def test_main_end_to_end(tmp_path):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        yaml.dump({"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}), encoding="utf-8"
    )

    output_path = tmp_path / "out.yaml"

    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["generate_db_scenarios.py", str(openapi_path), str(mapping_path), "-o", str(output_path)]
        code = gen_module.main()
    finally:
        _sys.argv = old_argv

    assert code == 0
    assert output_path.exists()
    loaded = load_scenarios(output_path)
    assert len(loaded) == 1


def test_main_missing_mapping_file_returns_1(tmp_path):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["generate_db_scenarios.py", str(openapi_path), str(tmp_path / "nope.yaml")]
        code = gen_module.main()
    finally:
        _sys.argv = old_argv

    assert code == 1


def test_main_invalid_openapi_returns_1(tmp_path):
    bad_openapi = tmp_path / "openapi.json"
    bad_openapi.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(yaml.dump({"operations": {}}), encoding="utf-8")

    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["generate_db_scenarios.py", str(bad_openapi), str(mapping_path)]
        code = gen_module.main()
    finally:
        _sys.argv = old_argv

    assert code == 1
