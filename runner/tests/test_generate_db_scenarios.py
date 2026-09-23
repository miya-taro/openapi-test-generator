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


# ---------- _resource_family ----------


def test_resource_family_groups_nested_paths_under_same_key():
    assert gen_module._resource_family("/orders") == "orders"
    assert gen_module._resource_family("/orders/{id}") == "orders"
    assert gen_module._resource_family("/orders/{id}/items") == "orders"


def test_resource_family_different_top_level_paths_differ():
    assert gen_module._resource_family("/categories") != gen_module._resource_family("/products")


# ---------- _singularize ----------


def test_singularize_handles_ies_plural():
    # 素朴な末尾"s"除去だと "categorie" になってしまい "category" に一致しなくなる
    # （回帰テスト: categoryId からの依存推測が効かなくなっていたバグ）
    assert gen_module._singularize("categories") == "category"


def test_singularize_handles_regular_plural():
    assert gen_module._singularize("orders") == "order"
    assert gen_module._singularize("products") == "product"


def test_singularize_handles_es_plural_after_double_s_or_sibilant():
    # 素朴な末尾"s"除去1文字だけだと "addresse"/"boxe"/"classe" になってしまい、
    # addressId 等のフィールド名からの依存推測に一致しなくなる回帰テスト。
    assert gen_module._singularize("addresses") == "address"
    assert gen_module._singularize("boxes") == "box"
    assert gen_module._singularize("classes") == "class"
    assert gen_module._singularize("wishes") == "wish"
    assert gen_module._singularize("churches") == "church"


def test_singularize_does_not_over_strip_e_ending_words():
    # "case" のように e で終わる語の複数形（cases）は +s のみ（+es 除去2文字にすると
    # "cas" という誤った語になってしまう）。ss/x/ch/sh で終わる語との判別が曖昧なため、
    # 誤検出が無いと確認できるケースのみ対応している（cases はそれ以外の代表例）。
    assert gen_module._singularize("cases") == "case"


# ---------- _infer_referenced_family ----------


def test_infer_referenced_family_detects_camel_case_id_field():
    mapping = {"category": "categories", "user": "users"}
    assert gen_module._infer_referenced_family("categoryId", mapping, self_family="products") == "categories"


def test_infer_referenced_family_ignores_plain_id_field():
    mapping = {"category": "categories"}
    assert gen_module._infer_referenced_family("id", mapping, self_family="categories") is None


def test_infer_referenced_family_ignores_self_reference():
    mapping = {"category": "categories"}
    assert gen_module._infer_referenced_family("categoryId", mapping, self_family="categories") is None


def test_infer_referenced_family_no_match_returns_none():
    mapping = {"category": "categories"}
    assert gen_module._infer_referenced_family("unrelatedId", mapping, self_family="products") is None


# ---------- 複数リソースファミリー間の依存関係を考慮した並び順 ----------

_MULTI_RESOURCE_OPENAPI = {
    "openapi": "3.1.0",
    "paths": {
        "/categories": {
            "post": {
                "operationId": "createCategory",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
        "/products": {
            "post": {
                "operationId": "createProduct",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}, "categoryId": {"type": "integer"}},
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
        "/orders": {
            "post": {
                "operationId": "createOrder",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "items": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"productId": {"type": "integer"}},
                                        },
                                    }
                                },
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
    },
}


def test_families_ordered_so_dependencies_come_first():
    # orders は items[].productId 経由で products に依存し、products は categoryId 経由で
    # categories に依存する。名前順（categories, orders, products）ではなく、依存関係順
    # （categories → products → orders）で並ぶ必要がある。
    mapping = {
        "createCategory": {"engine": "postgres", "table": "categories"},
        "createProduct": {"engine": "postgres", "table": "products"},
        "createOrder": {"engine": "postgres", "table": "orders"},
    }
    scenarios = gen_module._generate_scenarios(_MULTI_RESOURCE_OPENAPI, mapping)
    op_ids = [s["request"]["operationId"] for s in scenarios]
    assert op_ids.index("createCategory") < op_ids.index("createProduct")
    assert op_ids.index("createProduct") < op_ids.index("createOrder")


# ---------- 作成直後の読み取り確認（response_check）の自動挿入 ----------

_OPENAPI_WITH_GET_BY_ID = {
    "openapi": "3.1.0",
    "paths": {
        "/widgets": {
            "post": {
                "operationId": "createWidget",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "price": {"type": "number"},
                                    "tags": {"type": "array", "items": {"type": "string"}},
                                },
                            }
                        }
                    }
                },
                "responses": {"201": {"description": "Created"}},
            }
        },
        "/widgets/{widgetId}": {
            "get": {
                "operationId": "getWidget",
                "parameters": [
                    {"name": "widgetId", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "put": {
                "operationId": "updateWidget",
                "parameters": [
                    {"name": "widgetId", "in": "path", "required": True, "schema": {"type": "integer"}}
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "properties": {"name": {"type": "string"}}}
                        }
                    }
                },
                "responses": {"200": {"description": "OK"}},
            },
        },
    },
}


def test_find_get_by_id_operation_finds_well_formed_get():
    result = gen_module._find_get_by_id_operation(_OPENAPI_WITH_GET_BY_ID, "widgets")
    assert result is not None
    operation_id, get_op = result
    assert operation_id == "getWidget"


def test_find_get_by_id_operation_returns_none_without_path_param():
    api = {
        "openapi": "3.1.0",
        "paths": {"/widgets/{id}": {"get": {"operationId": "getWidget", "responses": {"200": {"description": "OK"}}}}},
    }
    assert gen_module._find_get_by_id_operation(api, "widgets") is None


def test_find_get_by_id_operation_returns_none_when_get_has_request_body():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/widgets/{id}": {
                "get": {
                    "operationId": "getWidget",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
                    "requestBody": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    "responses": {"200": {"description": "OK"}},
                }
            }
        },
    }
    assert gen_module._find_get_by_id_operation(api, "widgets") is None


def test_generate_scenarios_inserts_read_verification_right_after_create():
    mapping = {
        "createWidget": {"engine": "postgres", "table": "widgets"},
        "updateWidget": {"engine": "postgres", "table": "widgets"},
    }
    scenarios = gen_module._generate_scenarios(_OPENAPI_WITH_GET_BY_ID, mapping)
    op_ids = [s["request"]["operationId"] for s in scenarios]

    assert op_ids == ["createWidget", "getWidget", "updateWidget"]

    read_check = scenarios[1]
    assert read_check["request"]["path_params"] == {"widgetId": "{{response.id}}"}
    assert "db_check" not in read_check
    assert read_check["response_check"]["expect"]["status"] == 200
    # id は自動採番のため除外、name/price はcreateWidgetで送った値と一致する必要がある
    body = read_check["response_check"]["expect"]["body"]
    assert body["name"] == scenarios[0]["request"]["body"]["name"]
    assert "id" not in body
    assert "tags" not in body  # 配列はスカラー一致条件にならないため除外


def test_generate_scenarios_skips_read_verification_when_no_get_by_id_exists():
    api = {
        "openapi": "3.1.0",
        "paths": {
            "/widgets": {
                "post": {
                    "operationId": "createWidget",
                    "requestBody": {
                        "content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}
                    },
                    "responses": {"201": {"description": "Created"}},
                }
            }
        },
    }
    mapping = {"createWidget": {"engine": "postgres", "table": "widgets"}}
    scenarios = gen_module._generate_scenarios(api, mapping)
    assert [s["request"]["operationId"] for s in scenarios] == ["createWidget"]


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


def test_scenario_baseline_excludes_readonly_and_uses_default():
    openapi = {
        "openapi": "3.1.0",
        "paths": {
            "/tickets": {
                "post": {
                    "operationId": "createTicket",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer", "readOnly": True},
                                        "title": {"type": "string"},
                                        "status": {"type": "string", "default": "open"},
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
    mapping = {"operations": {"createTicket": {"engine": "postgres", "table": "tickets"}}}
    scenarios = gen_module._generate_scenarios(openapi, mapping["operations"])
    body = scenarios[0]["request"]["body"]
    assert "id" not in body
    assert body["status"] == "open"
    assert "title" in body


def test_where_excludes_id_and_nested_fields():
    mapping = {"operations": {"createPet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    where = scenarios[0]["db_check"]["where"]
    assert "id" not in where
    assert "category" not in where
    assert where["name"]
    assert where["status"] == "available"


def test_delete_scenario_expects_not_exists():
    s = gen_module._build_scenario(
        "deletePet", "delete", "/pets/{petId}",
        SAMPLE_OPENAPI["paths"]["/pets/{petId}"]["delete"],
        {"engine": "postgres", "table": "pets"}, is_first_in_family=True,
    )
    assert s["db_check"]["expect"]["exists"] is False


def test_isolated_update_scenario_with_no_preceding_scenario_uses_baseline_path_param():
    # deletePet/updatePet 単体（同ファミリー内に他の操作が無い）場合、
    # 引き継ぎ元となる直前のシナリオが存在しないため、ベースライン値で埋める
    # （存在しない{{response.id}}を参照する壊れたプレースホルダにはしない）。
    mapping = {"operations": {"updatePet": {"engine": "postgres", "table": "pets"}}}
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    assert scenarios[0]["request"]["path_params"]["petId"] != "{{response.id}}"
    assert isinstance(scenarios[0]["request"]["path_params"]["petId"], int)


def test_family_chaining_create_then_update_then_delete_in_lifecycle_order():
    # create/update/delete が全て対応表にある場合、同じ "pets" ファミリーとして
    # 作成→更新→削除の順に並び、2件目以降は {{response.id}} で引き継ぐ。
    mapping = {
        "operations": {
            "createPet": {"engine": "postgres", "table": "pets"},
            "updatePet": {"engine": "postgres", "table": "pets"},
            "deletePet": {"engine": "postgres", "table": "pets"},
        }
    }
    scenarios = gen_module._generate_scenarios(SAMPLE_OPENAPI, mapping["operations"])
    op_ids = [s["request"]["operationId"] for s in scenarios]
    assert op_ids == ["createPet", "updatePet", "deletePet"]

    create, update, delete = scenarios
    assert "path_params" not in create["request"]  # createPetはpath paramを持たない
    assert update["request"]["path_params"]["petId"] == "{{response.id}}"
    assert delete["request"]["path_params"]["petId"] == "{{response.id}}"


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


def test_main_end_to_end_with_read_verification_scenario(tmp_path):
    # 回帰テスト: main() の「engineの重複表記を間引く」処理が db_check の存在を前提に
    # しており、response_check のみのシナリオ（作成直後の読み取り確認）で
    # KeyError('db_check') になっていた。
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(_OPENAPI_WITH_GET_BY_ID), encoding="utf-8")

    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        yaml.dump({"operations": {"createWidget": {"engine": "postgres", "table": "widgets"}}}),
        encoding="utf-8",
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
    loaded = load_scenarios(output_path)
    assert len(loaded) == 2  # createWidget + 自動挿入されたgetWidgetの読み取り確認


# ---------- _dominant_engine ----------


def test_dominant_engine_single_engine():
    scenarios = [{"db_check": {"engine": "postgres"}}, {"db_check": {"engine": "postgres"}}]
    assert gen_module._dominant_engine(scenarios) == "postgres"


def test_dominant_engine_mixed_majority():
    scenarios = [
        {"db_check": {"engine": "postgres"}},
        {"db_check": {"engine": "postgres"}},
        {"db_check": {"engine": "influxdb"}},
    ]
    assert gen_module._dominant_engine(scenarios) == "postgres"


def test_dominant_engine_tie_prefers_postgres():
    scenarios = [{"db_check": {"engine": "influxdb"}}, {"db_check": {"engine": "postgres"}}]
    assert gen_module._dominant_engine(scenarios) == "postgres"


def test_dominant_engine_influxdb_majority():
    scenarios = [
        {"db_check": {"engine": "influxdb"}},
        {"db_check": {"engine": "influxdb"}},
        {"db_check": {"engine": "postgres"}},
    ]
    assert gen_module._dominant_engine(scenarios) == "influxdb"


def test_dominant_engine_empty_list_returns_none():
    assert gen_module._dominant_engine([]) is None


# ---------- main(): scenarios.defaults/list 形式での出力 ----------


def test_main_output_uses_defaults_list_structure(tmp_path):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        yaml.dump({
            "operations": {
                "createPet": {"engine": "postgres", "table": "pets"},
                "updatePet": {"engine": "postgres", "table": "pets"},
            }
        }),
        encoding="utf-8",
    )

    output_path = tmp_path / "out.yaml"
    old_argv = sys.argv
    try:
        sys.argv = ["generate_db_scenarios.py", str(openapi_path), str(mapping_path), "-o", str(output_path)]
        code = gen_module.main()
    finally:
        sys.argv = old_argv

    assert code == 0
    raw = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert raw["scenarios"]["defaults"] == {"engine": "postgres"}
    scenario_list = raw["scenarios"]["list"]
    assert len(scenario_list) == 2
    # 全シナリオがdefaultsと同じengineなので、個別のdb_checkからは省略されている
    assert all("engine" not in s["db_check"] for s in scenario_list)

    loaded = load_scenarios(output_path)
    assert len(loaded) == 2
    assert all(s.db_check.engine == "postgres" for s in loaded)


def test_main_output_keeps_explicit_engine_for_minority_engine(tmp_path):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        yaml.dump({
            "operations": {
                "createPet": {"engine": "postgres", "table": "pets"},
                "deletePet": {"engine": "postgres", "table": "pets"},
                "updatePet": {"engine": "influxdb", "measurement": "pet_updates"},
            }
        }),
        encoding="utf-8",
    )

    output_path = tmp_path / "out.yaml"
    old_argv = sys.argv
    try:
        sys.argv = ["generate_db_scenarios.py", str(openapi_path), str(mapping_path), "-o", str(output_path)]
        code = gen_module.main()
    finally:
        sys.argv = old_argv

    assert code == 0
    raw = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert raw["scenarios"]["defaults"] == {"engine": "postgres"}
    scenario_list = raw["scenarios"]["list"]

    by_op = {s["request"]["operationId"]: s for s in scenario_list}
    assert "engine" not in by_op["createPet"]["db_check"]
    assert "engine" not in by_op["deletePet"]["db_check"]
    assert by_op["updatePet"]["db_check"]["engine"] == "influxdb"

    loaded = load_scenarios(output_path)
    engines = {s.request.operation_id: s.db_check.engine for s in loaded}
    assert engines == {"createPet": "postgres", "deletePet": "postgres", "updatePet": "influxdb"}


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
