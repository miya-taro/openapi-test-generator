"""OpenAPI authentication-probe payload shared by generation, preview, and execution."""
from __future__ import annotations

import json

OPENAPI_SECURITY_PARAM = "__openapi_security__"
AUTH_NONE_MARKER = "（認証ヘッダなし）"
_LOCATIONS = ("headers", "query", "cookies")


def serialize_security_payload(payload: dict[str, dict[str, str]]) -> str:
    normalized = parse_security_payload(json.dumps(payload, ensure_ascii=False))
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def parse_security_payload(value: str) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("OpenAPI認証試験データのJSONが不正です") from exc

    if not isinstance(payload, dict) or set(payload) - set(_LOCATIONS):
        raise ValueError("OpenAPI認証試験データはheaders/query/cookiesだけを指定してください")

    normalized: dict[str, dict[str, str]] = {}
    for location in _LOCATIONS:
        entries = payload.get(location, {})
        if not isinstance(entries, dict):
            raise ValueError(f"OpenAPI認証試験データの{location}はオブジェクトである必要があります")
        if any(not isinstance(name, str) or not name or not isinstance(item, str) for name, item in entries.items()):
            raise ValueError(f"OpenAPI認証試験データの{location}は空でない名前と文字列値を指定してください")
        normalized[location] = entries
    return normalized
