"""multipart/form-data のファイルアップロードフィールド（type: string, format: binary）用ルール。

異常系の「必須フィールド欠落」は generate_common_cases が required から自動生成するため、
ここでは正常系（ダミーファイルをアップロードする）のみを扱う。ファイル内容そのものの
妥当性検証（拡張子・サイズ・MIME種別）はOpenAPI Validation Keywordsの範囲外のため対象外。
"""
from __future__ import annotations

# runner/request_builder.py の _FILE_UPLOAD_MARKER と対応させている。
FILE_UPLOAD_MARKER = "（ファイルアップロード：ダミーファイル）"


def generate_file_cases(ctx: dict) -> list[dict]:
    cases: list[dict] = []
    opts = ctx["opts"]

    if opts["includeNormal"]:
        cases.append({
            "summary": f"{ctx['paramName']} ファイルアップロード（正常）",
            "keyword": "format",
            "perspective": "正常系_ファイルアップロード",
            "inputValue": FILE_UPLOAD_MARKER,
            "expectedStatus": ctx.get("successStatus"),
            "expectedResult": "正常に処理されること",
            "notes": "ダミーファイルをアップロードする",
        })

    return cases
