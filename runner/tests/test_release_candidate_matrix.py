"""First-release qualification against independently implemented JSON API routes."""
import json
import os
import sys
import threading
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runner"))
from docs.release_candidate_api import CandidateServer, TOKEN
from http_client import execute_with_openapi
from models import RunCase
from response_schema import from_run_case
from verifier import verify
from src.parser import parse_openapi
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids

SPEC = ROOT / "docs/release_candidate_openapi.json"


def generated_cases(api):
    params, bodies = extract_specs(api)
    return assign_ids(generate_test_cases(params, bodies, {
        "includeNormal": True, "includeAbnormal": True, "enumFullCoverage": True,
    }, extract_auth_specs(api)))


def as_run_case(case):
    return RunCase(case["id"], case["operationId"], case["path"], case["method"], case["in"], case["paramName"],
                   case["inputValue"], case["expectedStatus"], case["expectedResponseBody"],
                   case["expectedResponseHeader"], case["expectedResponseTime"], case["expectedResult"])


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_TOKEN", TOKEN)
    monkeypatch.delenv("TEST_AUTH_HEADER_NAME", raising=False)
    monkeypatch.delenv("TEST_AUTH_HEADER_VALUE", raising=False)
    server = CandidateServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def execute(case, api, base_url):
    result = execute_with_openapi(case, base_url, api)
    verdict, detail = verify(result, from_run_case(case, api))
    return {"id": case.id, "operation": case.operation_id, "input": case.input_value, "status": result.actual_status,
            "expected_status": case.expected_status, "verdict": verdict, "detail": detail,
            "response": result.report_body, "request": result.curl_command}


def save_evidence(tmp_path, name, value):
    output = Path(os.environ.get("OTG_RELEASE_EVIDENCE_DIR", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def test_all_generated_contract_cases_against_independent_api(candidate, tmp_path):
    server, base_url = candidate
    api = parse_openapi(str(SPEC))
    cases = generated_cases(api)
    results = [execute(as_run_case(case), api, base_url) for case in cases]
    # Explicit expectations for business-dependent empty/error responses, never inferred by the generator.
    for operation, path, status in [("emptyError", "/empty-error", "400"), ("problem", "/problem", "422")]:
        case = RunCase("EXPLICIT-" + operation, operation, path, "GET", "operation", "__valid_request__", "", status, "", "", "", "")
        results.append(execute(case, api, base_url))
    save_evidence(tmp_path, "contract-matrix.json", results)
    save_evidence(tmp_path, "generated-cases.json", {"cases": cases})
    failures = [r for r in results if r["verdict"] != "OK"]
    assert not failures, json.dumps(failures, ensure_ascii=False, indent=2)
    assert {case["method"] for case in cases} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    assert any(r["status"] == 204 for r in results)
    assert any(r["status"] == 401 for r in results) and any(r["status"] == 403 for r in results)
    assert any(call["path"] == "/catalog/日本語" for call in server.calls)
    assert any(call["body"] and isinstance(call["body"], dict) and call["body"].get("enabled") is False for call in server.calls)
    print(f"Independent API matrix: {len(results)} HTTP cases, {dict(Counter(r['operation'] for r in results))}")


def test_each_fault_is_detected_without_breaking_other_cases(candidate, tmp_path):
    server, base_url = candidate
    api = parse_openapi(str(SPEC))
    cases = generated_cases(api)
    faults = {
        "server_error": "catalog", "undocumented_error": "catalog", "missing_header": "catalog",
        "header_type": "catalog", "wrong_media": "catalog", "missing_property": "catalog",
        "wrong_type": "catalog", "wrong_nested": "createProfile", "extra_property": "replaceSettings",
        "bad_item": "numbers", "null_required": "catalog", "bad_datetime": "emptyOk", "bad_json": "catalog",
        "ignore_auth": "secure", "accept_invalid": "replaceSettings",
    }
    evidence = []
    for fault, operation in faults.items():
        abnormal = fault in {"ignore_auth", "accept_invalid"}
        selected = next(c for c in cases if c["operationId"] == operation and
                        ((str(c["expectedStatus"]).startswith("4") if abnormal else c["in"] == "operation")))
        case = as_run_case(selected)
        server.fault = "none"
        assert execute(case, api, base_url)["verdict"] == "OK", fault
        server.fault = fault
        result = execute(case, api, base_url)
        evidence.append({"fault": fault, **result})
        assert result["verdict"] == "NG", json.dumps(result, ensure_ascii=False)
    save_evidence(tmp_path, "detected-faults.json", evidence)
    print(f"Independent API matrix: {len(evidence)} faulty implementations detected")
