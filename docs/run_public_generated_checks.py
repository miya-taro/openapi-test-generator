#!/usr/bin/env python3
"""Generate all cases from the crates.io pagination contract; opt into HTTP with --execute."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runner"))
from docs.run_public_api_checks import to_run_case
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.parser import parse_openapi
from src.renderer.excel_output import write_excel_output
from excel_writer import write_results
from http_client import execute_with_openapi
from junit_writer import write_junit_xml
from request_builder import build_url
from response_schema import from_run_case
from verifier import verify

SPEC = ROOT / "docs/public-crates-pagination.openapi.json"
BASE_URL = "https://crates.io"


def prepare():
    api = parse_openapi(str(SPEC))
    params, bodies = extract_specs(api)
    cases = assign_ids(generate_test_cases(params, bodies, {
        "includeNormal": True, "includeAbnormal": True, "enumFullCoverage": True,
    }))
    for case in cases:
        # Public response latency is not an application performance requirement.
        case["expectedResponseTime"] = ""
    return api, cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Send all generated cases sequentially, at least one second apart")
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".artifacts/public-generated")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    api, cases = prepare()
    meta = {"source": str(SPEC), "generatedAt": datetime.now(timezone.utc).isoformat(),
            "totalCases": len(cases), "normalCases": sum(c["perspective"].startswith("正常") for c in cases),
            "abnormalCases": sum(c["perspective"].startswith("異常") for c in cases)}
    spec_excel = output / "spec.xlsx"
    write_excel_output({"cases": cases, "meta": meta}, str(spec_excel))
    (output / "generated-cases.json").write_text(json.dumps({"meta": meta, "cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "openapi.json").write_bytes(SPEC.read_bytes())
    # Do not send the user's API credentials to the public registry.
    for key in ("TEST_AUTH_TOKEN", "TEST_AUTH_HEADER_NAME", "TEST_AUTH_HEADER_VALUE"):
        os.environ.pop(key, None)
    results, evidence = [], []
    stopped = None
    if args.execute:
        with requests.Session() as session:
            session.headers["User-Agent"] = "openapi-test-generator/0.1 (https://github.com/miya-taro/openapi-test-generator)"
            for case in cases:
                time.sleep(1)
                run_case = to_run_case(case)
                result = execute_with_openapi(run_case, BASE_URL, api, session)
                verdict, detail = verify(result, from_run_case(run_case, api))
                results.append((result, verdict, detail))
                evidence.append({"id": case["id"], "summary": case["summary"], "keyword": case["keyword"],
                                 "perspective": case["perspective"], "parameter": case["paramName"],
                                 "input": case["inputValue"], "url": build_url(BASE_URL, run_case, api),
                                 "expected_status": case["expectedStatus"], "status": result.actual_status,
                                 "verdict": verdict, "detail": detail, "error": result.error,
                                 "request": result.curl_command, "response": result.report_body})
                print(case["id"], case["summary"], case["inputValue"], result.actual_status, verdict, detail[:300], flush=True)
                if result.error or result.actual_status in {403, 429}:
                    stopped = "Transport/access/rate limit failure; remaining cases not executed"
                    break
        write_results(spec_excel, results, output / "result.xlsx", full_body=True)
        write_junit_xml(results, output / "junit.xml", suite_name="public-generated-crates")
    summary = {"mode": "executed" if args.execute else "prepared-only", "time": datetime.now(timezone.utc).isoformat(),
               "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(), "generated": len(cases),
               "normal": meta["normalCases"], "abnormal": meta["abnormalCases"],
               "keywords": dict(Counter(c["keyword"] for c in cases)), "executed": len(results),
               "passed": sum(verdict == "OK" for _, verdict, _ in results), "stopped": stopped, "results": evidence}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(cases)}; executed {len(results)}; artifacts: {output}")
    return 0 if not args.execute or (len(results) == len(cases) and summary["passed"] == len(cases)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
