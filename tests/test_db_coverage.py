from src.db_coverage import build_db_coverage, execution_summary


def case(body, **checks):
    return {
        "caseId": "DB-1",
        "kind": "db-scenario",
        "source": {"operationId": "set"},
        "definition": {
            "request": {"body": body},
            "responseCheck": {"expectedStatus": 200},
            **checks,
        },
    }


def coverage(properties, cases, required=()):
    api = {
        "paths": {
            "/set": {
                "post": {
                    "operationId": "set",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": properties,
                                    "required": list(required),
                                }
                            }
                        }
                    },
                    "responses": {},
                }
            }
        }
    }
    return build_db_coverage(api, cases)


def test_missing_mapping_is_not_hidden_by_success_case():
    rows = coverage(
        {"value": {"type": "number"}, "other": {"type": "string"}},
        [
            case(
                {"value": 2},
                dbInsertCheck={
                    "columns": {"rate": {"kind": "request", "path": "value"}}
                },
            )
        ],
    )
    mappings = {r["field"]: r for r in rows if r["location"] == "DB保存"}
    assert mappings["value"]["caseIds"] == ["DB-1"]
    assert mappings["other"]["status"] == "未照合"
    assert mappings["other"]["caseIds"] == []


def test_optional_missing_differs_from_null_and_false_differs_from_zero():
    rows = coverage(
        {"flag": {"type": "boolean"}}, [case({"flag": 0}), case({"flag": None})]
    )
    conditions = [r for r in rows if r["keyword"].startswith("正常条件")]
    assert len(conditions) == 3
    assert all(r["status"] == "ケース未設定" for r in conditions)


def test_enum_strings_do_not_collide_with_array_count_markers():
    rows = coverage(
        {"type": {"enum": ["__one__"]}}, [case({"type": "__one__"})], ["type"]
    )
    assert next(r for r in rows if r["keyword"].startswith("正常条件"))["caseIds"] == [
        "DB-1"
    ]


def test_legacy_mapping_requires_manual_review():
    rows = coverage(
        {"value": {"type": "number"}}, [case({"value": 2}, dbCheck={"table": "values"})]
    )
    assert next(r for r in rows if r["location"] == "DB保存")["status"] == "要手動確認"


def test_partial_execution_never_becomes_all_passed():
    assert (
        execution_summary(
            {"caseIds": ["a", "b", "c", "d"]},
            {"a": "passed", "b": "skipped", "c": "warning"},
        )
        == "合格 1件 / 未確認 1件 / スキップ 1件 / 未実行 1件"
    )
    assert execution_summary({"caseIds": []}, {}) == "未試験（対応ケースなし）"
