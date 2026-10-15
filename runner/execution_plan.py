"""Executable adapters for the reviewed case master (never read spreadsheet cells)."""
from __future__ import annotations

import hashlib
import json

from db_scenario import parse_scenarios
from models import RunCase
from workflow.case_master import CaseMasterError, load_case_master


def load_plan(path, kind, case_ids=()):
    master = load_case_master(path)
    context = master.get("execution", {})
    api = context.get("openapi")
    digest = hashlib.sha256(json.dumps(
        api, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    if context.get("version") != 1 or not isinstance(api, dict) or digest != context.get("contractSha256"):
        raise CaseMasterError("実行用のAPI定義がありません、または変更されています。ケースを再準備してください")
    cases = [case for case in master["cases"] if case["kind"] == kind]
    if case_ids:
        missing = set(case_ids) - {case["caseId"] for case in cases}
        if missing:
            raise CaseMasterError("試験IDが見つかりません: " + ", ".join(sorted(missing)))
        cases = [case for case in cases if case["caseId"] in case_ids]
    if not cases:
        raise CaseMasterError("実行する試験ケースがありません")
    for case in cases:
        if case["source"].get("contractSha256") != digest:
            raise CaseMasterError("試験ケースとAPI定義が一致しません。ケースを再準備してください")
        # Parse every case before any HTTP/DB side effects.
        contract_case(case) if kind == "contract" else db_case(case)
    return master, cases, api


def contract_raw(case):
    definition, expected = case["definition"], case["expected"]
    request = definition["request"]
    return {
        "id": case["caseId"], "operationId": case["source"]["operationId"],
        "summary": case["title"], "method": request["method"], "path": request["path"],
        "in": request["location"], "paramName": request["name"], "inputValue": request["value"],
        "keyword": definition.get("keyword", ""), "perspective": definition.get("perspective", ""),
        "notes": definition.get("notes", ""), "expectedStatus": expected.get("status", ""),
        "expectedResponseBody": expected.get("body", ""), "expectedResponseHeader": expected.get("headers", ""),
        "expectedResponseTime": expected.get("responseTime", ""), "expectedResult": expected.get("result", ""),
    }


def contract_case(case):
    raw = contract_raw(case)
    return RunCase(*("" if raw[key] is None else str(raw[key]) for key in (
        "id", "operationId", "path", "method", "in", "paramName", "inputValue", "expectedStatus",
        "expectedResponseBody", "expectedResponseHeader", "expectedResponseTime", "expectedResult",
    )))


def db_case(case):
    """Invert the normalized definition through the same validated authoring parser."""
    definition = case["definition"]
    req = definition["request"]
    raw = {"id": case["caseId"], "name": case["title"], "request": {
        "operationId": req["operationId"], "body": req.get("body", {}),
        "path_params": req.get("pathParams", {}), "query_params": req.get("queryParams", {}),
    }, "given": definition.get("given", [])}
    for key, target in (
        ("authProfile", "auth_profile"), ("testFixture", "test_fixture"), ("ruleTest", "rule_test"),
        ("dbInsertCheck", "db_insert_check"), ("influxMutation", "influx_mutation"),
        ("dbSqlResponseCheck", "db_sql_response_check"), ("dbUnchanged", "db_unchanged"),
    ):
        if key in definition:
            raw[target] = definition[key]
    check = definition.get("responseCheck")
    if check is not None:
        raw["response_check"] = {"expect": {
            "status": check.get("expectedStatus"), "body": check.get("expectedBody", {}),
            "contains": check.get("expectedContains", []), "values": check.get("expectedValues", []),
            "collections": check.get("collections", []), "empty_body": check.get("emptyBody", False),
        }}
    for key, target, renames in (
        ("dbCheck", "db_check", {"rawSql": "raw_sql", "timeRange": "time_range"}),
        ("dbResponseCheck", "db_response_check", {"arrayPath": "array_path"}),
        ("cleanup", "cleanup", {"primaryKey": "primary_key"}),
    ):
        if definition.get(key) is not None:
            raw[target] = {renames.get(k, k): v for k, v in definition[key].items()}
    scenario = parse_scenarios(json.dumps({"scenarios": [raw]}, ensure_ascii=False))[0]
    scenario.case_id_override = case["caseId"]
    return scenario
