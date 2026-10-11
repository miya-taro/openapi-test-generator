"""Independent contract-case audit. Uses raw schemas as an oracle, not generator keywords."""

import os
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "runner"))
from jsonschema import Draft202012Validator, FormatChecker
from src.parser import parse_openapi
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.coverage import build_coverage
from models import RunCase
from request_builder import build_request_body
from http_client import execute_with_openapi
from response_schema import from_run_case
from verifier import verify
import requests

OUT = Path(os.environ["OTG_AUDIT_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
OPTS = {
    "includeNormal": True,
    "includeAbnormal": True,
    "enumFullCoverage": True,
    "oneOfFullCoverage": True,
}
FIELDS = {
    "string_type": {"type": "string"},
    "string_length": {"type": "string", "minLength": 2, "maxLength": 4},
    "string_enum": {"type": "string", "enum": ["red", "green", "blue"]},
    "string_pattern": {"type": "string", "pattern": "^[A-Z]{2}$"},
    "datetime": {"type": "string", "format": "date-time"},
    "integer_bounds": {"type": "integer", "minimum": 2, "maximum": 5},
    "number_bounds": {"type": "number", "minimum": 0.2, "maximum": 0.5},
    "integer_enum": {"type": "integer", "enum": [1, 2, 3]},
    "integer_multiple_one": {"type": "integer", "multipleOf": 1},
    "integer_combined": {
        "type": "integer",
        "minimum": 10,
        "maximum": 20,
        "multipleOf": 3,
    },
    "number_narrow": {
        "type": "number",
        "exclusiveMinimum": 0,
        "exclusiveMaximum": 0.01,
    },
    "boolean": {"type": "boolean"},
    "boolean_enum": {"type": "boolean", "enum": [False]},
    "nullable": {"type": ["string", "null"]},
    "optional": {"type": "string"},
    "array_bounds": {
        "type": "array",
        "items": {"type": "integer", "minimum": 1},
        "minItems": 1,
        "maxItems": 3,
        "uniqueItems": True,
    },
    "string_array": {"type": "array", "items": {"type": "string"}},
    "object_extra_string": {
        "type": "object",
        "additionalProperties": {"type": "string"},
    },
    "object_extra_false": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
    },
    "object_count": {
        "type": "object",
        "minProperties": 1,
        "maxProperties": 2,
        "additionalProperties": {"type": "integer"},
    },
    "const": {"type": "integer", "const": 7},
    "oneof": {
        "oneOf": [
            {"type": "integer", "minimum": 1, "maximum": 3},
            {"type": "string", "minLength": 2, "maxLength": 4},
        ]
    },
}
SCHEMAS = {
    name: {
        "type": "object",
        "properties": {"v": schema},
        "required": [] if name == "optional" else ["v"],
    }
    for name, schema in FIELDS.items()
}
RESP = {
    str(code): {
        "description": str(code),
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                }
            }
        },
    }
    for code in (200, 400)
}
raw = {
    "openapi": "3.1.0",
    "info": {"title": "Independent test-item audit", "version": "1"},
    "paths": {
        "/" + name: {
            "post": {
                "operationId": name,
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": schema}},
                },
                "responses": RESP,
            }
        }
        for name, schema in SCHEMAS.items()
    },
}
(OUT / "audit-openapi.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
api = parse_openapi(str(OUT / "audit-openapi.json"))
params, bodies = extract_specs(api)
cases = assign_ids(generate_test_cases(params, bodies, OPTS, extract_auth_specs(api)))


def rc(c):
    return RunCase(
        c["id"],
        c["operationId"],
        c["path"],
        c["method"],
        c["in"],
        c["paramName"],
        c["inputValue"],
        c["expectedStatus"],
        c["expectedResponseBody"],
        c["expectedResponseHeader"],
        c["expectedResponseTime"],
        c["expectedResult"],
    )


records = []
for c in cases:
    prepared = build_request_body(rc(c), api)
    body = prepared.json_body if prepared else None
    valid = bool(prepared) and Draft202012Validator(
        SCHEMAS[c["operationId"]], format_checker=FormatChecker()
    ).is_valid(body)
    records.append(
        {
            **c,
            "body": body,
            "body_present": prepared is not None,
            "oracle_valid": valid,
            "label_correct": valid == str(c["expectedStatus"]).startswith("2"),
        }
    )

# Each check is an independently stated obligation, fulfilled only by an actual request
# with the right expected outcome and an otherwise valid/invalid raw-schema oracle result.
checks = []


def need(op, label, positive, predicate):
    found = [
        r["id"]
        for r in records
        if r["operationId"] == op
        and r["label_correct"]
        and r["oracle_valid"] == positive
        and predicate(r)
    ]
    checks.append(
        {
            "operation": op,
            "obligation": label,
            "expected": "valid" if positive else "invalid",
            "covered": bool(found),
            "caseIds": found,
        }
    )


def val(r):
    return r["body"].get("v") if isinstance(r["body"], dict) else None


def scalar(op, label, value, positive=True):
    need(
        op,
        label,
        positive,
        lambda r: (
            isinstance(r["body"], dict)
            and "v" in r["body"]
            and type(val(r)) is type(value)
            and val(r) == value
        ),
    )


for op in FIELDS:
    need(op, "valid request", True, lambda r: True)
    need(op, "body absent", False, lambda r: not r["body_present"])
    if op != "optional":
        need(
            op,
            "required field absent",
            False,
            lambda r: isinstance(r["body"], dict) and "v" not in r["body"],
        )
scalar("string_type", "numeric value rejected", 123, False)
need(
    "string_type",
    "any non-null wrong JSON type",
    False,
    lambda r: (
        isinstance(r["body"], dict)
        and "v" in r["body"]
        and val(r) is not None
        and not isinstance(val(r), str)
    ),
)
for n, positive in [(1, False), (2, True), (4, True), (5, False)]:
    need(
        "string_length",
        f"length {n}",
        positive,
        lambda r, n=n: isinstance(val(r), str) and len(val(r)) == n,
    )
for v in ["red", "green", "blue"]:
    scalar("string_enum", f"enum {v}", v)
need(
    "string_enum",
    "same-type value outside enum",
    False,
    lambda r: isinstance(val(r), str) and val(r) not in FIELDS["string_enum"]["enum"],
)
for v, p in [(1, False), (2, True), (5, True), (6, False)]:
    scalar("integer_bounds", f"bound {v}", v, p)
need(
    "integer_bounds",
    "fractional number rejected",
    False,
    lambda r: type(val(r)) is float and not val(r).is_integer(),
)
for v in [1, 2, 3]:
    scalar("integer_enum", f"enum {v}", v)
need(
    "integer_enum",
    "integer outside enum",
    False,
    lambda r: type(val(r)) is int and val(r) not in [1, 2, 3],
)
for v in [12, 15, 18]:
    scalar("integer_combined", f"valid lattice value {v}", v)
for v in [True, False]:
    scalar("boolean", f"value {v}", v)
scalar("boolean_enum", "true rejected", True, False)
scalar("nullable", "null accepted", None, True)
need(
    "optional",
    "optional field absent",
    True,
    lambda r: isinstance(r["body"], dict) and "v" not in r["body"],
)
for n, p in [(0, False), (1, True), (3, True), (4, False)]:
    need(
        "array_bounds",
        f"length {n}",
        p,
        lambda r, n=n: isinstance(val(r), list) and len(val(r)) == n,
    )
need(
    "array_bounds",
    "duplicate otherwise valid items rejected",
    False,
    lambda r: (
        isinstance(val(r), list)
        and len(val(r)) != len(set(map(str, val(r))))
        and all(type(x) is int and x >= 1 for x in val(r))
    ),
)
need(
    "string_array",
    "non-null non-string element rejected",
    False,
    lambda r: (
        isinstance(val(r), list)
        and any(x is not None and not isinstance(x, str) for x in val(r))
    ),
)
need(
    "object_extra_string",
    "non-null non-string additional value rejected",
    False,
    lambda r: (
        isinstance(val(r), dict)
        and any(x is not None and not isinstance(x, str) for x in val(r).values())
    ),
)
need(
    "const",
    "same-type wrong constant rejected",
    False,
    lambda r: type(val(r)) is int and val(r) != 7,
)
for n, p in [(1, False), (2, True), (4, True), (5, False)]:
    need(
        "oneof",
        f"string branch length {n}",
        p,
        lambda r, n=n: isinstance(val(r), str) and len(val(r)) == n,
    )

# Run real HTTP cases against an independently checking API and mutants that accept
# exactly one forbidden input class. Public APIs are not changed or fuzzed here.
calls = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        op = self.path.strip("/")
        text = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            body = json.loads(text) if text else None
        except ValueError:
            body = None
        valid = bool(text) and Draft202012Validator(
            SCHEMAS[op], format_checker=FormatChecker()
        ).is_valid(body)
        value = body.get("v") if isinstance(body, dict) else None
        mode = self.server.mode
        if (
            mode == "accept_number_for_string"
            and op == "string_type"
            and type(value) in (int, float)
        ):
            valid = True
        if (
            mode == "ignore_integer_enum"
            and op == "integer_enum"
            and type(value) is int
        ):
            valid = True
        if (
            mode == "ignore_boolean_enum"
            and op == "boolean_enum"
            and type(value) is bool
        ):
            valid = True
        if (
            mode == "ignore_string_branch_max"
            and op == "oneof"
            and isinstance(value, str)
            and len(value) >= 2
        ):
            valid = True
        status = 200 if valid else 400
        calls.append({"mode": mode, "operation": op, "body": body, "status": status})
        payload = json.dumps({"ok": valid}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server.mode = "strict"
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
http_results = []
mutants = []
try:
    for c in cases:
        result = execute_with_openapi(rc(c), base, api)
        verdict, detail = verify(result, from_run_case(rc(c), api))
        http_results.append(
            {
                "id": c["id"],
                "operation": c["operationId"],
                "summary": c["summary"],
                "expectedStatus": c["expectedStatus"],
                "actualStatus": result.actual_status,
                "verdict": verdict,
                "detail": detail,
            }
        )
    for mode, op, witness in [
        ("accept_number_for_string", "string_type", {"v": 123}),
        ("ignore_integer_enum", "integer_enum", {"v": 4}),
        ("ignore_boolean_enum", "boolean_enum", {"v": True}),
        ("ignore_string_branch_max", "oneof", {"v": "12345"}),
    ]:
        server.mode = "strict"
        strict = requests.post(base + "/" + op, json=witness).status_code
        server.mode = mode
        faulty = requests.post(base + "/" + op, json=witness).status_code
        results = []
        for c in [c for c in cases if c["operationId"] == op]:
            actual = execute_with_openapi(rc(c), base, api)
            verdict, detail = verify(actual, from_run_case(rc(c), api))
            results.append({"id": c["id"], "verdict": verdict, "detail": detail})
        mutants.append(
            {
                "fault": mode,
                "operation": op,
                "manual_witness": witness,
                "strict_status": strict,
                "faulty_status": faulty,
                "generated_cases": len(results),
                "detected": any(r["verdict"] == "NG" for r in results),
                "results": results,
            }
        )
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)

# User's GET JSON-body example: independently check conditional presence truth tables.
measure = parse_openapi(str(ROOT / "examples/measure-get-openapi.json"))
p, b = extract_specs(measure)
mcases = assign_ids(generate_test_cases(p, b, OPTS, extract_auth_specs(measure)))
measure_records = []
for c in mcases:
    prepared = build_request_body(rc(c), measure)
    measure_records.append({**c, "body": prepared.json_body if prepared else None})
measure_checks = []
for names, allowed in [
    (("site_id", "location_id"), [False, True, True, True]),
    (("start", "end"), [True, False, False, True]),
]:
    for (first, second), expected in zip(
        [(False, False), (True, False), (False, True), (True, True)],
        allowed,
        strict=True,
    ):
        matching = [
            r["id"]
            for r in measure_records
            if r["keyword"] == "conditionalRequired"
            and isinstance(r["body"], dict)
            and (names[0] in r["body"], names[1] in r["body"]) == (first, second)
            and str(r["expectedStatus"]).startswith("2") == expected
            and r["inputValue"].startswith(
                "__PRESENCE_RULE__" + ("0" if names[0] == "site_id" else "1") + ":"
            )
        ]
        measure_checks.append(
            {
                "fields": names,
                "present": [first, second],
                "expected_valid": expected,
                "covered": bool(matching),
                "caseIds": matching,
            }
        )

result = {
    "source_commit": __import__("subprocess")
    .check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True)
    .strip(),
    "operations": len(FIELDS),
    "generated_cases": len(cases),
    "obligations": checks,
    "label_mismatches": [r for r in records if not r["label_correct"]],
    "http_results": http_results,
    "mutants": mutants,
    "coverage": build_coverage(api, cases),
    "measure_checks": measure_checks,
    "measure_cases": measure_records,
}
for name, data in [
    ("audit-result.json", result),
    ("generated-cases.json", records),
    ("http-calls.json", calls),
]:
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    json.dumps(
        {
            "operations": len(FIELDS),
            "cases": len(cases),
            "obligations": len(checks),
            "covered": sum(x["covered"] for x in checks),
            "missing": [x for x in checks if not x["covered"]],
            "label_mismatch_count": len(result["label_mismatches"]),
            "strict_http_failures": [r for r in http_results if r["verdict"] != "OK"],
            "undetected_mutants": [r["fault"] for r in mutants if not r["detected"]],
            "measure_truth_table": measure_checks,
        },
        ensure_ascii=False,
        indent=2,
    )
)
