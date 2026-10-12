"""Independent, disposable JSON API used to qualify the first release.

Request checks are implemented here without importing the generator or reading
its OpenAPI schemas. State is local to each server; no external service is used.
"""
from __future__ import annotations

import json
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit


TOKEN = "release-test-token"


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def integer(value):
    return number(value) and int(value) == value


def text(value, minimum=0, maximum=100):
    return isinstance(value, str) and minimum <= len(value) <= maximum


def profile_valid(body):
    if not isinstance(body, dict) or set(body) != {"name", "address", "labels"}:
        return False
    address, labels = body["address"], body["labels"]
    return (text(body["name"], 1, 8) and isinstance(address, dict) and set(address) == {"city", "zip"}
            and text(address["city"], 1, 8) and isinstance(address["zip"], str) and re.fullmatch(r"[0-9]{5}", address["zip"])
            and isinstance(labels, list) and 1 <= len(labels) <= 3
            and all(text(v, 1, 4) for v in labels) and len(set(labels)) == len(labels))


def settings_valid(body, patch):
    if not isinstance(body, dict) or not body or set(body) - {"enabled", "threshold", "note"}:
        return False
    if not patch and not {"enabled", "threshold", "note"}.issubset(body):
        return False
    return (('enabled' not in body or isinstance(body['enabled'], bool))
            and ('threshold' not in body or number(body['threshold']) and 0 <= body['threshold'] <= 10)
            and ('note' not in body or body['note'] is None or text(body['note'], 0, 4)))


class CandidateServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.fault = "none"
        self.calls = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, body=None, media="application/json", headers=None):
        headers = {"X-Quota": "3", **(headers or {})}
        fault = self.server.fault
        if fault == "server_error": status = 500
        if fault == "undocumented_error": status, body = 409, {"error": "conflict"}
        if fault == "missing_header": headers.pop("X-Quota", None)
        if fault == "header_type": headers["X-Quota"] = "not-a-number"
        if fault == "wrong_media": media = "text/plain"
        if fault == "missing_property": body = {}
        if fault == "wrong_type": body = {"total": "2", "data": []}
        if fault == "wrong_nested": body = {"id": 1, "profile": {"name": "A", "address": {"city": 123, "zip": "12345"}, "labels": ["a"]}}
        if fault == "extra_property": body = {"enabled": True, "threshold": 1, "note": None, "unexpected": True}
        if fault == "bad_item": body = [1, "wrong"]
        if fault == "null_required": body = {"total": None, "data": []}
        if fault == "bad_datetime": body = {"time": "not-a-date", "items": []}
        if fault == "bad_json": encoded = b'{"broken":'
        else: encoded = b"" if status == 204 else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if status != 204: self.send_header("Content-Type", media)
        for name, value in headers.items(): self.send_header(name, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def execute(self):
        path = unquote(urlsplit(self.path).path)
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try: body = json.loads(raw) if raw else None
        except ValueError: body = None
        self.server.calls.append({"method": self.command, "path": path, "query": query, "body": body})
        if path == "/health": return self.respond(200, {"ok": True})
        if path == "/secure":
            auth = self.headers.get("Authorization")
            if self.server.fault != "ignore_auth" and auth != "Bearer " + TOKEN:
                return self.respond(401 if not auth else 403, {"error": "authentication"})
            return self.respond(200, {"user": "tester"})
        if path == "/empty-error": return self.respond(400, {"error": "no data"})
        if path == "/problem": return self.respond(422, {"title": "invalid", "status": 422}, "application/problem+json")
        valid, result, success = True, {}, 200
        if path == "/catalog":
            limits, flags, tags = query.get("limit", []), query.get("active", []), query.get("tag", [])
            valid = (len(limits) == 1 and re.fullmatch(r"[0-9]+", limits[0]) and 1 <= int(limits[0]) <= 3
                     and len(flags) == 1 and flags[0] in ["true", "false"]
                     and 1 <= len(tags) <= 2 and all(v in ["red", "blue"] for v in tags))
            result = {"total": 2, "data": [{"id": 1, "name": "日本語"}, {"id": 2, "name": "A"}]}
        elif path.startswith("/catalog/"):
            valid = path[len("/catalog/"):] in ["A 1", "日本語"]
            result = {"id": 1, "name": "日本語"}
        elif path == "/profiles" and self.command == "POST":
            valid, success = profile_valid(body), 201
            result = {"id": 1, "profile": body}
        elif path == "/numbers":
            valid = (isinstance(body, list) and 1 <= len(body) <= 3
                     and all(number(v) and 0 <= v <= 100 and v * 2 == int(v * 2) for v in body)
                     and len(set(body)) == len(body))
            result = body
        elif path == "/settings":
            valid = settings_valid(body, self.command == "PATCH")
            result = {"enabled": True, "threshold": 1, "note": None, **(body if isinstance(body, dict) else {})}
        elif path.startswith("/profiles/") and self.command == "DELETE":
            id_ = path[len("/profiles/"):]
            valid, success = bool(re.fullmatch(r"[0-9]+", id_)) and 1 <= int(id_) <= 9, 204
        elif path == "/session":
            cookie = SimpleCookie()
            cookie.load(self.headers.get("Cookie", ""))
            valid = (self.headers.get("X-Tenant") == "north" and "session" in cookie and cookie["session"].value == "session-a")
            result = {"ok": True}
        elif path == "/empty-ok":
            result = {"time": "2026-10-11T00:00:00Z", "items": []}
        else:
            return self.respond(404, {"error": "route"})
        if path in {"/profiles", "/numbers", "/settings"} and self.command in {"POST", "PUT", "PATCH"}:
            valid = valid and self.headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json"
        if self.server.fault == "accept_invalid":
            valid = True
            result = {"enabled": True, "threshold": 1, "note": None}
        if not valid:
            return self.respond(422, {"error": "validation"})
        return self.respond(success, result)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = execute
