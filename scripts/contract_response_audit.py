"""Response, auth inventory, and user's GET-body API checks for the coverage audit."""

import copy
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "runner")]
from jsonschema import Draft202012Validator, FormatChecker
from src.parser import parse_openapi
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.coverage import build_coverage
from models import RunCase, RunResult
from response_schema import from_run_case
from verifier import verify
from http_client import execute_with_openapi
import requests

OUT = Path(os.environ["OTG_AUDIT_OUTPUT"])
OUT.mkdir(parents=True, exist_ok=True)
OPTS = {
    "includeNormal": True,
    "includeAbnormal": True,
    "enumFullCoverage": True,
    "oneOfFullCoverage": True,
}


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


# Independently chosen response violations, passed through the real verifier.
responses = []


def response_check(label, schema, payload, expected="NG", status=200, headers=None):
    doc = {
        "paths": {
            "/r": {
                "get": {
                    "operationId": "r",
                    "responses": {
                        "200": {
                            "headers": {
                                "X-Count": {
                                    "required": True,
                                    "schema": {"type": "integer", "minimum": 0},
                                }
                            },
                            "content": {"application/json": {"schema": schema}},
                        },
                        "400": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["error"],
                                        "properties": {"error": {"type": "string"}},
                                    }
                                }
                            }
                        },
                    },
                }
            }
        }
    }
    case = RunCase(
        "response-" + str(len(responses)),
        "r",
        "/r",
        "GET",
        "operation",
        "__valid_request__",
        "",
        "2xx" if status < 400 else "4xx",
        "",
        "",
        "",
        "",
    )
    result = RunResult(
        case,
        status,
        payload,
        headers
        if headers is not None
        else {"Content-Type": "application/json", "X-Count": "0"},
        1,
        0,
    )
    verdict, detail = verify(result, from_run_case(case, doc))
    responses.append(
        {
            "check": label,
            "expected": expected,
            "actual": verdict,
            "correct": expected == verdict,
            "payload": payload,
            "detail": detail,
        }
    )


obj = {
    "type": "object",
    "required": ["v"],
    "properties": {"v": {"type": "string"}},
    "additionalProperties": False,
}
response_check("valid response", obj, '{"v":"ok"}', "OK")
response_check("required response field", obj, "{}")
response_check("response string accepts number", obj, '{"v":123}')
response_check("response extra field", obj, '{"v":"ok","extra":1}')
response_check("invalid JSON", obj, "{bad")
response_check("missing Content-Type", obj, '{"v":"ok"}', headers={"X-Count": "0"})
response_check(
    "wrong Content-Type",
    obj,
    '{"v":"ok"}',
    headers={"Content-Type": "text/plain", "X-Count": "0"},
)
response_check(
    "missing required header",
    obj,
    '{"v":"ok"}',
    headers={"Content-Type": "application/json"},
)
response_check(
    "header type",
    obj,
    '{"v":"ok"}',
    headers={"Content-Type": "application/json", "X-Count": "abc"},
)
response_check(
    "header minimum",
    obj,
    '{"v":"ok"}',
    headers={"Content-Type": "application/json", "X-Count": "-1"},
)
response_check("documented 400 body", obj, '{"error":"bad"}', "OK", status=400)
response_check("undocumented 409", obj, '{"error":"bad"}', status=409)
response_check("400 response schema", obj, '{"error":123}', status=400)
for label, definition, good, bad in [
    ("string min", {"type": "string", "minLength": 2}, "ab", "a"),
    ("string max", {"type": "string", "maxLength": 2}, "ab", "abc"),
    ("string pattern", {"type": "string", "pattern": "^[A-Z]{2}$"}, "AB", "a1"),
    ("integer enum", {"type": "integer", "enum": [1, 2]}, 1, 3),
    ("number min", {"type": "number", "minimum": 0}, 0, -1),
    ("number exclusive max", {"type": "number", "exclusiveMaximum": 1}, 0.9, 1),
    ("multipleOf", {"type": "integer", "multipleOf": 3}, 6, 7),
    ("integer fractional", {"type": "integer"}, 1, 1.5),
    ("boolean", {"type": "boolean"}, False, 0),
    (
        "date-time",
        {"type": "string", "format": "date-time"},
        "2026-01-01T00:00:00Z",
        "2026-02-30T00:00:00Z",
    ),
    ("array element", {"type": "array", "items": {"type": "string"}}, ["a"], [1]),
    (
        "array unique",
        {"type": "array", "items": {"type": "integer"}, "uniqueItems": True},
        [1, 2],
        [1, 1],
    ),
    ("array min", {"type": "array", "minItems": 1}, [1], []),
    ("object count", {"type": "object", "minProperties": 1}, {"a": 1}, {}),
    (
        "oneOf exclusivity",
        {"oneOf": [{"type": "integer"}, {"type": "number", "minimum": 0}]},
        -1,
        1,
    ),
    ("nullable", {"type": ["string", "null"]}, None, 1),
]:
    response_check(label + " valid", definition, json.dumps(good), "OK")
    response_check(label + " invalid", definition, json.dumps(bad))
response_check("NaN is not valid JSON", {"type": "number"}, "NaN")
response_check("Infinity is not valid JSON", {"type": "number"}, "Infinity")

# Security AND definitions require each credential, not just none/all-bad.
auth_doc = {
    "openapi": "3.1.0",
    "info": {"title": "Auth audit", "version": "1"},
    "components": {
        "securitySchemes": {
            "first": {"type": "apiKey", "in": "header", "name": "X-First"},
            "second": {"type": "apiKey", "in": "header", "name": "X-Second"},
        }
    },
    "paths": {
        "/secure": {
            "get": {
                "operationId": "secure",
                "security": [{"first": [], "second": []}],
                "responses": {
                    "200": {"description": "OK"},
                    "401": {"description": "Auth"},
                },
            }
        }
    },
}
p, b = extract_specs(auth_doc)
acases = assign_ids(generate_test_cases(p, b, OPTS, extract_auth_specs(auth_doc)))
auth_inventory = {"cases": acases, "coverage": build_coverage(auth_doc, acases)}

# User's API: run all generated cases on correct and deliberately faulty implementations.
measure = parse_openapi(str(ROOT / "examples/measure-get-openapi.json"))
p, b = extract_specs(measure)
mcases = assign_ids(generate_test_cases(p, b, OPTS, extract_auth_specs(measure)))
raw = json.loads((ROOT / "examples/measure-get-openapi.json").read_text(encoding="utf-8"))
raw_schema = raw["paths"]["/v1/result/measure/get"]["get"]["requestBody"]["content"][
    "application/json"
]["schema"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer audit-valid":
            status, payload = 401, {"error": "auth"}
        else:
            text = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                body = json.loads(text) if text else None
            except ValueError:
                body = None
            checked = copy.deepcopy(body)
            if isinstance(checked, dict):
                if self.server.mode == "location_number" and type(
                    checked.get("location_id")
                ) in (int, float):
                    checked["location_id"] = str(checked["location_id"])
                if self.server.mode == "item_number" and isinstance(
                    checked.get("items"), list
                ):
                    checked["items"] = [
                        str(x) if type(x) in (int, float) else x
                        for x in checked["items"]
                    ]
                if (
                    self.server.mode == "site_fraction"
                    and type(checked.get("site_id")) is float
                ):
                    checked["site_id"] = int(checked["site_id"])
            valid = Draft202012Validator(
                raw_schema, format_checker=FormatChecker()
            ).is_valid(checked)
            if valid:
                valid = bool("site_id" in checked or "location_id" in checked) and (
                    ("start" in checked) == ("end" in checked)
                )
            if valid:
                status = 200
                payload = {
                    "site_id": checked.get("site_id", 0),
                    "start": checked.get("start", "2026-01-01T00:00:00Z"),
                    "end": checked.get("end", "2026-01-01T00:00:00Z"),
                    "result": [],
                }
            else:
                status, payload = 400, {"error": "invalid"}
        content = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Result-Count", "0")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server.mode = "strict"
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f"http://127.0.0.1:{server.server_port}"
measure_results = []
old = os.environ.get("TEST_AUTH_TOKEN")
os.environ["TEST_AUTH_TOKEN"] = "audit-valid"
try:
    for mode, witness in [
        ("strict", None),
        ("location_number", {"location_id": 123, "items": ["temperature"]}),
        ("item_number", {"site_id": 1, "items": [123]}),
        ("site_fraction", {"site_id": 1.5, "items": ["temperature"]}),
    ]:
        server.mode = mode
        results = []
        for c in mcases:
            r = execute_with_openapi(rc(c), base, measure)
            v, d = verify(r, from_run_case(rc(c), measure))
            results.append(
                {
                    "id": c["id"],
                    "verdict": v,
                    "detail": d,
                    "actualStatus": r.actual_status,
                }
            )
        direct = {}
        if witness:
            server.mode = "strict"
            direct["strict"] = requests.get(
                base + "/v1/result/measure/get",
                json=witness,
                headers={"Authorization": "Bearer audit-valid"},
            ).status_code
            server.mode = mode
            direct["faulty"] = requests.get(
                base + "/v1/result/measure/get",
                json=witness,
                headers={"Authorization": "Bearer audit-valid"},
            ).status_code
        measure_results.append(
            {
                "mode": mode,
                "witness": witness,
                "witness_status": direct,
                "cases": len(results),
                "failures": [r for r in results if r["verdict"] != "OK"],
            }
        )
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
    if old is None:
        os.environ.pop("TEST_AUTH_TOKEN", None)
    else:
        os.environ["TEST_AUTH_TOKEN"] = old

out = {
    "response_checks": responses,
    "auth_inventory": auth_inventory,
    "measure_http": measure_results,
}
(OUT / "extra-audit-result.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(
    json.dumps(
        {
            "response_checks": len(responses),
            "response_mismatches": [r for r in responses if not r["correct"]],
            "auth_cases": [(c["keyword"], c["inputValue"]) for c in acases],
            "auth_coverage_keywords": [
                r["keyword"] for r in auth_inventory["coverage"]
            ],
            "measure_http": measure_results,
        },
        ensure_ascii=False,
        indent=2,
    )
)
