#!/usr/bin/env python3
"""Prepare, or explicitly execute, 18 public REST API compatibility checks.

Targets hosted JSONPlaceholder/httpbin, not locally recreated implementations.
Default mode only writes the reviewable cases and OpenAPI; --execute sends HTTP.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import requests
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runner"))
from docs.run_public_api_checks import obj, to_run_case
from src.parser import parse_openapi
from src.renderer.excel_output import write_excel_output
from request_builder import build_url, build_request_body
from http_client import execute_with_openapi
from response_schema import from_run_case
from verifier import verify
from excel_writer import write_results
from junit_writer import write_junit_xml

HOSTS = {"jsonplaceholder": "https://jsonplaceholder.typicode.com", "httpbin": "https://httpbin.org"}
TEXT = {"type": "string"}
INT = {"type": "integer"}
POST = {"title": "otg-public-test", "body": "API compatibility check", "userId": 1}
ECHO = {"name": "日本語", "enabled": False, "optional": None,
        "items": [{"id": 1, "value": 1.5}, {"id": 2, "value": 0}]}
FIXTURE = ROOT / "docs/fixtures/jsonplaceholder-posts.json"


def profiles():
    specs = {key: {"openapi": "3.1.0", "info": {"title": f"{key} selected public test contracts", "version": "1"},
                   "servers": [{"url": host}], "paths": {}} for key, host in HOSTS.items()}
    cases = {key: [] for key in HOSTS}

    def add(provider, name, method, path, status, response=None, body=None, location="operation", parameter="__valid_request__", value="", expected=None):
        responses = specs[provider]["paths"].setdefault(path, {}).setdefault(method.lower(), {
            "operationId": name, "responses": {},
        })
        operation_id = responses["operationId"]
        declared = {"description": f"Expected public API status {status}"}
        if response is not None:
            Draft202012Validator.check_schema(response)
            declared["content"] = {"application/json": {"schema": response}}
        responses["responses"][str(status)] = declared
        if body is not None:
            responses["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"type": "object", "example": body}}}}
            location, parameter, value = "body", "requestBody", json.dumps(body, ensure_ascii=False)
        elif location in {"query", "cookie"}:
            responses["parameters"] = [{"name": parameter, "in": location, "schema": TEXT}]
        cases[provider].append({
            "id": f"PUBLIC-{provider}-{len(cases[provider]) + 1:02}", "operationId": operation_id,
            "summary": name, "path": path, "method": method, "in": location, "paramName": parameter,
            "keyword": "explicit-public-contract", "perspective": "正常系" if status < 400 else "異常系",
            "inputValue": value, "expectedStatus": expected or str(status), "expectedResponseBody": "Declared response schema",
            "expectedResponseHeader": "", "expectedResponseTime": "", "expectedResult": "公開APIの明示した契約に一致する",
            "notes": "Human-authored compatibility case; no inference of persistent DB state", "verdict": "",
        })

    expected_posts = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]
    first_post = next(post for post in expected_posts if post["id"] == 1)
    add("jsonplaceholder", "readPost", "GET", "/posts/1", 200, {"const": first_post})
    add("jsonplaceholder", "filterPosts", "GET", "/posts", 200,
        {"type": "array", "minItems": len(expected_posts), "maxItems": len(expected_posts),
         "uniqueItems": True, "items": {"enum": expected_posts}}, location="query", parameter="userId", value="1")
    add("jsonplaceholder", "missingPost", "GET", "/posts/999999999", 404, {"type": "object"})
    add("jsonplaceholder", "createPost", "POST", "/posts", 201,
        obj({"id": INT, **{key: {"const": value} for key, value in POST.items()}}), body=POST)
    add("jsonplaceholder", "replacePost", "PUT", "/posts/1", 200,
        obj({"id": {"const": 1}, **{key: {"const": value} for key, value in POST.items()}}), body=POST)
    add("jsonplaceholder", "patchPost", "PATCH", "/posts/1", 200,
        {"const": {**first_post, "title": "otg-patched"}}, body={"title": "otg-patched"})
    add("jsonplaceholder", "deletePost", "DELETE", "/posts/1", 200, {"type": "object", "maxProperties": 0})
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        add("httpbin", "echo" + method, method, "/" + method.lower(), 200, obj({"json": {"const": ECHO}}), body=ECHO)
    add("httpbin", "getJsonBody", "GET", "/anything", 200, obj({"method": {"const": "GET"}, "json": {"const": ECHO}}), body=ECHO)
    add("httpbin", "requestHeader", "GET", "/headers", 200, obj({"headers": obj({"X-Otg-Test": {"const": "public-check"}})}),
        location="header", parameter="X-Otg-Test", value="public-check")
    add("httpbin", "requestCookie", "GET", "/cookies", 200, obj({"cookies": obj({"otg_test": {"const": "public-check"}})}),
        location="cookie", parameter="otg_test", value="public-check")
    add("httpbin", "emptyResponse", "GET", "/status/204", 204)
    add("httpbin", "bearerPresent", "GET", "/bearer", 200, obj({"authenticated": {"const": True}}),
        location="header", parameter="Authorization", value="Bearer public-demo-token")
    add("httpbin", "bearerMissing", "GET", "/bearer", 401,
        location="header", parameter="Authorization", value="（省略）")
    add("httpbin", "documentedError", "GET", "/status/400", 400, expected="4xx")
    return specs, cases


def response_controls(result, case, api):
    """Offline mutations of the measured response; never extra public requests."""
    payload = json.loads(result.actual_body)
    variants = []
    name = case["summary"]
    if name == "readPost":
        variants = [("wrong_id", {**payload, "id": 999}, "NG")]
    elif name == "filterPosts":
        variants = [
            ("reordered", list(reversed(payload)), "OK"),
            ("empty", [], "NG"), ("missing_row", payload[:-1], "NG"),
            ("duplicate_row", payload[:-1] + [payload[0]], "NG"),
            ("extra_row", payload + [payload[0]], "NG"),
        ]
        for field, value, label in [("id", 999, "wrong_id"), ("userId", 2, "wrong_owner"),
                                    ("title", "unexpected", "wrong_content")]:
            changed = deepcopy(payload)
            changed[0][field] = value
            variants.append((label, changed, "NG"))
        changed = deepcopy(payload)
        changed[-1]["id"] = payload[0]["id"]
        variants.append(("duplicate_id_different_content", changed, "NG"))
    elif name == "patchPost":
        variants = [("unrelated_field_changed", {**payload, "body": "unexpected"}, "NG")]
    outcomes = []
    for label, body, expected in variants:
        altered = replace(result, actual_body=json.dumps(body, ensure_ascii=False), report_body=None)
        verdict, detail = verify(altered, from_run_case(to_run_case(case), api))
        outcomes.append({"case_id": case["id"], "mutation": label, "expected": expected,
                         "verdict": verdict, "detail": detail[:1000]})
    return outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send 18 sequential public HTTP requests; mutations are simulated by JSONPlaceholder")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts/public-rest")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for key in ("TEST_AUTH_TOKEN", "TEST_AUTH_HEADER_NAME", "TEST_AUTH_HEADER_VALUE"):
        os.environ.pop(key, None)
    specs, groups = profiles()
    prepared, evidence, controls = [], [], []
    with requests.Session() as session:
        session.headers["User-Agent"] = "openapi-test-generator/0.1 (https://github.com/miya-taro/openapi-test-generator)"
        for provider, spec in specs.items():
            spec_path = output / f"{provider}-openapi.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            api = parse_openapi(str(spec_path))
            cases = groups[provider]
            spec_excel = output / f"{provider}-spec.xlsx"
            write_excel_output({"cases": cases, "meta": {
                "source": str(spec_path), "generatedAt": datetime.now(timezone.utc).isoformat(), "totalCases": len(cases),
                "normalCases": sum(int(c["expectedStatus"][0]) < 4 for c in cases),
                "abnormalCases": sum(int(c["expectedStatus"][0]) >= 4 for c in cases),
            }}, str(spec_excel))
            results = []
            for case in cases:
                run_case = to_run_case(case)
                body = build_request_body(run_case, api)
                prepared.append({"provider": provider, "id": case["id"], "name": case["summary"], "method": case["method"],
                                 "url": build_url(HOSTS[provider], run_case, api), "body": body.json_body if body else None,
                                 "expected_status": case["expectedStatus"]})
                if not args.execute:
                    continue
                time.sleep(1)
                result = execute_with_openapi(run_case, HOSTS[provider], api, session)
                verdict, detail = verify(result, from_run_case(run_case, api))
                if verdict == "OK" and case["summary"] in {"readPost", "filterPosts", "patchPost"}:
                    controls.extend(response_controls(result, case, api))
                results.append((result, verdict, detail))
                evidence.append({**prepared[-1], "status": result.actual_status, "verdict": verdict, "detail": detail,
                                 "request": result.curl_command, "response": result.report_body, "error": result.error})
                print(provider, case["id"], result.actual_status, verdict, detail[:400], flush=True)
            if args.execute:
                write_results(spec_excel, results, output / f"{provider}-result.xlsx", full_body=True)
                write_junit_xml(results, output / f"{provider}-junit.xml", suite_name=f"public-{provider}")
    (output / "prepared-cases.json").write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"mode": "executed" if args.execute else "prepared-only", "time": datetime.now(timezone.utc).isoformat(),
               "prepared": len(prepared), "executed": len(evidence), "passed": sum(row["verdict"] == "OK" for row in evidence),
               "results": evidence, "offline_response_controls": controls}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(prepared)}; executed {len(evidence)}; artifacts: {output}")
    return 0 if not args.execute or (summary["passed"] == 18 and len(controls) == 11
                                    and all(c["expected"] == c["verdict"] for c in controls)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
