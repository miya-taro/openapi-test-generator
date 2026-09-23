"""認証ルール（認証なし / 無効トークン）。"""
from __future__ import annotations

from src.security_payload import AUTH_NONE_MARKER, OPENAPI_SECURITY_PARAM, serialize_security_payload


def _security_schemes(spec: dict) -> list[dict]:
    schemes = spec.get("securitySchemes")
    if schemes:
        return schemes
    return [{
        "schemeName": spec.get("headerName", "Authorization"),
        "schemeType": spec["schemeType"],
        "in": "header",
        "name": spec.get("headerName", "Authorization"),
    }]


def _invalid_auth_value() -> str:
    # 認証方式が異なる候補も同時に無効化するため、Authorization prefixを付けず
    # Bearer/Basic/APIキーのいずれにも有効にならない値を使う。
    return "invalid-token-xxx"


def _security_failure_status(spec: dict) -> str:
    responses = spec.get("responsesInfo") or {}
    if "401" in responses:
        return "401"
    if "403" in responses:
        return "403"
    return "401"


def generate_auth_cases(spec: dict) -> list[dict]:
    schemes = _security_schemes(spec)
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    cookies: dict[str, str] = {}
    for scheme in schemes:
        target = {"header": headers, "query": query, "cookie": cookies}.get(scheme.get("in"))
        if target is not None:
            target[scheme.get("name") or "Authorization"] = _invalid_auth_value()

    expected_status = _security_failure_status(spec)
    scheme_summary = ", ".join(
        f"{scheme.get('schemeName', scheme.get('name'))}（{scheme.get('in')}: {scheme.get('name')}）"
        for scheme in schemes
    )
    payload = serialize_security_payload({"headers": headers, "query": query, "cookies": cookies})

    return [
        {
            "summary": f"{spec['operationId']} 認証なし（異常）",
            "keyword": "auth",
            "perspective": "異常系_認証なし",
            "paramName": OPENAPI_SECURITY_PARAM,
            "inputValue": AUTH_NONE_MARKER,
            "expectedStatus": expected_status,
            "expectedResult": "認証エラーが返ること",
            "notes": "OpenAPIに定義された認証情報を送信しない",
        },
        {
            "summary": f"{spec['operationId']} 無効な認証情報（異常）",
            "keyword": "auth",
            "perspective": "異常系_無効トークン",
            "paramName": OPENAPI_SECURITY_PARAM,
            "inputValue": payload,
            "expectedStatus": expected_status,
            "expectedResult": "認証エラーが返ること",
            "notes": f"全ての認証候補に無効値を送信する: {scheme_summary}",
        },
    ]
