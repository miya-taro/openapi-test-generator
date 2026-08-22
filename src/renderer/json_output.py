"""JSON 出力（test_cases.json）。"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


def build_output(cases: list[dict], source: str) -> dict:
    normal_cases = sum(1 for c in cases if c["perspective"].startswith("正常系"))
    abnormal_cases = sum(1 for c in cases if c["perspective"].startswith("異常系"))

    return {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source": source,
            "totalCases": len(cases),
            "normalCases": normal_cases,
            "abnormalCases": abnormal_cases,
        },
        "cases": cases,
    }


def write_output(output: dict, output_path: str) -> None:
    Path(output_path).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
