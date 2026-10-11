#!/usr/bin/env python3
"""Opt-in, low-volume GET checks against public package registry JSON APIs.

Uses this application's generator, HTTP client, verifier and Excel/JUnit writers.
No network access occurs on import, in pytest, or in the normal CI suite.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runner"))
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.parser import parse_openapi
from src.renderer.excel_output import write_excel_output
from excel_writer import write_results
from http_client import execute_with_openapi
from junit_writer import write_junit_xml
from models import RunCase
from response_schema import from_run_case
from verifier import verify

MISSING = "otg-public-api-check-no-such-package-6f07c5e57dbb4c9a"
STRING = {"type": "string"}
INTEGER = {"type": "integer"}
DATETIME = {"type": "string", "format": "date-time"}
BASE_URLS = {"pypi": "https://pypi.org", "npm": "https://registry.npmjs.org", "crates": "https://crates.io"}


def obj(properties):
    return {"type": "object", "required": list(properties), "properties": properties}


def array(items):
    return {"type": "array", "items": items}


def parameter(name, sample):
    return {"name": name, "in": "path", "required": True, "schema": {**STRING, "example": sample}}


def operation(name, parameters, schema, error_schema=None):
    responses = {"200": {"description": "Documented JSON response subset", "content": {"application/json": {"schema": schema}}},
                 "404": {"description": "Resource not found"}}
    if error_schema:
        responses["404"]["content"] = {"application/json": {"schema": error_schema}}
    return {"get": {"operationId": name, "parameters": parameters, "responses": responses}}


def specifications():
    # Authored contract subsets from official docs; not inferred from fetched response bodies.
    pypi = obj({"info": obj({"name": STRING, "version": STRING}), "last_serial": INTEGER,
                "urls": array(obj({"filename": STRING, "size": INTEGER, "upload_time_iso_8601": DATETIME,
                                   "digests": obj({"sha256": STRING})})), "vulnerabilities": array({"type": "object"})})
    npm = obj({"name": STRING, "version": STRING, "dist": obj({"tarball": {"type": "string", "format": "uri"}, "shasum": STRING})})
    search = obj({"objects": array(obj({"package": obj({"name": STRING, "version": STRING})})), "total": INTEGER, "time": DATETIME})
    crates = obj({"crate": obj({"id": STRING, "name": STRING, "downloads": INTEGER, "updated_at": DATETIME}),
                  "versions": array(obj({"id": INTEGER, "num": STRING, "yanked": {"type": "boolean"}}))})
    paths = {
        "pypi": {
            "/pypi/{project}/json": operation("pypiProject", [parameter("project", "requests")], pypi),
            "/pypi/{project}/{version}/json": operation("pypiRelease", [parameter("project", "sampleproject"), parameter("version", "4.0.0")], pypi),
        },
        "npm": {
            "/{package}/{version}": operation("npmVersion", [parameter("package", "is-number"), parameter("version", "latest")], npm),
            "/-/v1/search": operation("npmSearch", [{"name": "text", "in": "query", "schema": STRING}], search),
        },
        "crates": {"/api/v1/crates/{crate}": operation("crateDetail", [parameter("crate", "serde")], crates, obj({"errors": array(obj({"detail": STRING}))}))},
    }
    return {name: {"openapi": "3.1.0", "info": {"title": f"{name} public API contract subset", "version": "1"},
                   "servers": [{"url": BASE_URLS[name]}], "paths": value} for name, value in paths.items()}


def to_run_case(case):
    return RunCase(case["id"], case["operationId"], case["path"], case["method"], case["in"], case["paramName"],
                   case["inputValue"], case["expectedStatus"], case["expectedResponseBody"], case["expectedResponseHeader"], "", case["expectedResult"])


def selected_cases(api, provider):
    params, bodies = extract_specs(api)
    all_cases = assign_ids(generate_test_cases(params, bodies, {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}))
    baselines = {case["operationId"]: case for case in all_cases if case["in"] == "operation"}
    choices = {
        "pypi": [("pypiProject", None, None, None), ("pypiProject", "project", "sampleproject", "200"),
                 ("pypiRelease", None, None, None), ("pypiProject", "project", MISSING, "404")],
        "npm": [("npmVersion", None, None, None), ("npmVersion", "package", "is-odd", "200"),
                ("npmVersion", "version", "7.0.0", "200"), ("npmSearch", "text", "is-number", "200"),
                ("npmVersion", "package", MISSING, "404")],
        "crates": [("crateDetail", None, None, None), ("crateDetail", "crate", "itoa", "200"),
                   ("crateDetail", "crate", MISSING, "404")],
    }
    result = []
    for index, (op, name, value, status) in enumerate(choices[provider], start=1):
        case = deepcopy(baselines[op])
        case["id"] = f"PUBLIC-{provider}-{index:02}"
        case["expectedResponseTime"] = ""  # External latency is not a performance requirement.
        case["notes"] = "Generated baseline" if name is None else "Explicit public-resource example"
        if name:
            case.update(paramName=name, inputValue=value, expectedStatus=status,
                        perspective="異常系_存在しない対象" if status == "404" else "正常系_公開データ",
                        expectedResponseBody="Declared response contract", expectedResponseHeader="", keyword="public-example")
            case["in"] = "query" if name == "text" else "path"
        result.append(case)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send exactly 12 sequential public GET requests")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts/public-api")
    args = parser.parse_args()
    if not args.execute:
        parser.error("Pass --execute to opt into public network access")
    # Never forward credentials for the user's API to unrelated public services.
    for key in ("TEST_AUTH_TOKEN", "TEST_AUTH_HEADER_NAME", "TEST_AUTH_HEADER_VALUE"):
        os.environ.pop(key, None)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence, negative_controls = [], []
    with requests.Session() as session:
        session.headers["User-Agent"] = "openapi-test-generator/0.1 (https://github.com/miya-taro/openapi-test-generator)"
        for provider, spec in specifications().items():
            spec_path = output / f"{provider}-openapi.json"
            spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
            api = parse_openapi(str(spec_path))
            cases = selected_cases(api, provider)
            spec_excel = output / f"{provider}-spec.xlsx"
            write_excel_output({"cases": cases, "meta": {
                "source": str(spec_path), "generatedAt": datetime.now(timezone.utc).isoformat(),
                "totalCases": len(cases), "normalCases": len(cases) - 1, "abnormalCases": 1,
            }}, str(spec_excel))
            results = []
            for case in cases:
                time.sleep(1)  # Low volume, sequential; no retries or fuzzing of public infrastructure.
                run_case = to_run_case(case)
                result = execute_with_openapi(run_case, BASE_URLS[provider], api, session)
                verdict, detail = verify(result, from_run_case(run_case, api))
                results.append((result, verdict, detail))
                evidence.append({"provider": provider, "id": case["id"], "method": "GET", "path": case["path"],
                                 "input": case["inputValue"], "expected": case["expectedStatus"], "actual": result.actual_status,
                                 "verdict": verdict, "detail": detail, "error": result.error, "elapsed_ms": result.elapsed_ms,
                                 "request": result.curl_command, "response": result.report_body})
                print(provider, case["id"], result.actual_status, verdict, detail, flush=True)
                # Offline controls reuse a captured response, making no additional HTTP requests.
                if case == cases[0] and verdict == "OK":
                    for name, mutate in [
                        ("wrong_status", lambda s: (setattr(s, "expected_status_class", None), setattr(s, "expected_statuses", frozenset({201})))),
                        ("wrong_body_type", lambda s: setattr(s, "expected_body_schemas_by_status_and_content_type", {200: {"application/json": {"type": "array"}}})),
                    ]:
                        contract = from_run_case(run_case, api)
                        mutate(contract)
                        control_verdict, control_detail = verify(result, contract)
                        negative_controls.append({"provider": provider, "control": name, "verdict": control_verdict, "detail": control_detail})
            write_results(spec_excel, results, output / f"{provider}-result.xlsx", full_body=True)
            write_junit_xml(results, output / f"{provider}-junit.xml", suite_name=f"public-{provider}")
    summary = {"run_at": datetime.now(timezone.utc).isoformat(), "http_requests": len(evidence),
               "passed": sum(row["verdict"] == "OK" for row in evidence), "results": evidence, "offline_negative_controls": negative_controls}
    (output / "evidence.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Evidence: {output}")
    return 0 if summary["passed"] == len(evidence) and len(negative_controls) == 6 and all(row["verdict"] == "NG" for row in negative_controls) else 1


if __name__ == "__main__":
    raise SystemExit(main())
