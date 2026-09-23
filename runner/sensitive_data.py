"""Redact credential-like values before test evidence is written to reports."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping

WRITE_ONLY_SCHEMA_MARKER = "x-api-tester-write-only"

KNOWN_CREDENTIAL_PATTERNS = (
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_.-]{20,}|github_pat_[A-Za-z0-9_.-]{20,})\b"),
        "GitHub形式のトークン露出",
    ),
    (re.compile(r"\bxox[bpasr]-[A-Za-z0-9-]{12,}\b"), "Slack形式のトークン露出"),
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), "AWSアクセスキーIDの露出"),
    (
        re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
        "Stripe形式のAPIキー露出",
    ),
)

PRIVATE_KEY_HEADER = re.compile(
    r"-----BEGIN (?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY-----|"
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----",
    re.IGNORECASE,
)
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?P<kind>(?:(?:RSA|EC|DSA|OPENSSH|ENCRYPTED) )?PRIVATE KEY)-----"
    r".*?-----END (?P=kind)-----|"
    r"-----BEGIN PGP PRIVATE KEY BLOCK-----.*?-----END PGP PRIVATE KEY BLOCK-----",
    re.IGNORECASE | re.DOTALL,
)

_SENSITIVE_JSON_NAMES = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "clientsecret",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "apikey",
    "privatekey",
    "authorization",
    "cookie",
    "setcookie",
    "session",
    "sessionid",
    "csrf",
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>\b(?:password|passwd|pwd|secret|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|"
    r"private[_-]?key|session[_-]?id|csrf[_-]?token|token)\b\s*[:=]\s*)"
    r"(?:(?P<quote>[\"'])(?P<quoted_value>.*?)(?P=quote)|"
    r"(?P<bare_value>[^\s,;}\]]+))"
)
_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "apikey",
    "xapikey",
    "authtoken",
    "xauthtoken",
    "accesstoken",
    "xaccesstoken",
    "refreshtoken",
    "xrefreshtoken",
}


def credential_findings(text: str) -> list[str]:
    """Return provider labels only; never include matched credential values."""
    return [
        finding
        for pattern, finding in KNOWN_CREDENTIAL_PATTERNS
        if pattern.search(text)
    ]


def contains_private_key_header(text: str) -> bool:
    return bool(PRIVATE_KEY_HEADER.search(text))


def redact_sensitive_text(text: str) -> str:
    return redact_sensitive_response(text)


def redact_sensitive_response(text: str, schema: dict | None = None) -> str:
    """Redact known secrets and schema-declared writeOnly values for report evidence."""
    if not isinstance(text, str):
        return ""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        changed = False
    else:
        parsed, schema_changed = _redact_with_schema(parsed, schema)
        parsed, key_changed = _redact_json_value(parsed)
        changed = schema_changed or key_changed
        if changed:
            text = json.dumps(parsed, ensure_ascii=False)

    text = PRIVATE_KEY_BLOCK.sub("[REDACTED:PRIVATE_KEY]", text)
    for pattern, _finding in KNOWN_CREDENTIAL_PATTERNS:
        text = pattern.sub("[REDACTED:CREDENTIAL]", text)
    return _SENSITIVE_ASSIGNMENT.sub(_redact_assignment, text)


def redact_header_value(name: str, value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    if normalized in _SENSITIVE_HEADER_NAMES or normalized.endswith(
        ("token", "secret", "apikey", "password", "cookie")
    ):
        return "[REDACTED]"
    return redact_sensitive_text(value)


def _redact_json_value(value: object) -> tuple[object, bool]:
    if isinstance(value, Mapping):
        redacted: dict[object, object] = {}
        changed = False
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if _is_sensitive_json_name(normalized) and item is not None:
                redacted[key] = "[REDACTED]"
                changed = True
                continue
            redacted[key], item_changed = _redact_json_value(item)
            changed |= item_changed
        return redacted, changed
    if isinstance(value, list):
        redacted_items = [_redact_json_value(item) for item in value]
        return [item for item, _ in redacted_items], any(changed for _, changed in redacted_items)
    return value, False


def _redact_with_schema(value: object, schema: dict | None) -> tuple[object, bool]:
    if not isinstance(schema, dict):
        return value, False

    changed = False
    variants = schema.get("_oneOfVariants")
    if isinstance(variants, list):
        for variant in variants:
            value, variant_changed = _redact_with_schema(value, variant)
            changed |= variant_changed

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        additional = schema.get("additionalProperties")
        redacted: dict[object, object] = {}
        for key, item in value.items():
            property_schema = properties.get(key) if isinstance(properties, dict) else None
            if isinstance(property_schema, dict) and property_schema.get(WRITE_ONLY_SCHEMA_MARKER):
                redacted[key] = "[REDACTED]"
                changed = True
                continue
            child_schema = property_schema if isinstance(property_schema, dict) else None
            if child_schema is None and isinstance(additional, dict):
                child_schema = additional
            redacted[key], child_changed = _redact_with_schema(item, child_schema)
            changed |= child_changed
        return redacted, changed

    if isinstance(value, list):
        item_schema = schema.get("items")
        redacted_items = [_redact_with_schema(item, item_schema) for item in value]
        return [item for item, _ in redacted_items], changed or any(
            item_changed for _, item_changed in redacted_items
        )

    return value, changed


def _is_sensitive_json_name(normalized: str) -> bool:
    return normalized in _SENSITIVE_JSON_NAMES or normalized.endswith(
        ("password", "passwd", "secret", "token", "apikey", "privatekey")
    )


def _redact_assignment(match: re.Match[str]) -> str:
    prefix = match.group("prefix")
    quote = match.group("quote")
    if quote:
        return f"{prefix}{quote}[REDACTED]{quote}"
    return f"{prefix}[REDACTED]"
