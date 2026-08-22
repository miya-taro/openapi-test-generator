"""認証ルール（認証なし / 無効トークン）。"""
from __future__ import annotations


def generate_auth_cases(spec: dict) -> list[dict]:
    scheme_type = spec["schemeType"]
    if scheme_type == "bearer":
        invalid_value = "Bearer invalid-token-xxx"
    elif scheme_type == "basic":
        invalid_value = "Basic aW52YWxpZA=="
    else:
        invalid_value = "invalid-token-xxx"

    return [
        {
            "summary": f"{spec['operationId']} 認証なし（異常）",
            "keyword": "auth",
            "perspective": "異常系_認証なし",
            "inputValue": "（認証ヘッダなし）",
            "expectedStatus": "401",
            "expectedResult": "認証エラーが返ること",
            "notes": f"{spec['headerName']} ヘッダを送信しない",
        },
        {
            "summary": f"{spec['operationId']} 無効な認証トークン（異常）",
            "keyword": "auth",
            "perspective": "異常系_無効トークン",
            "inputValue": invalid_value,
            "expectedStatus": "401",
            "expectedResult": "認証エラーが返ること",
            "notes": f"無効な {spec['headerName']} を送信する",
        },
    ]
