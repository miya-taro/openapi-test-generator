"""Real HTTP mutation tests: correct servers pass and each known defect must fail."""

import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def audit(script, tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        cwd=ROOT,
        env={**os.environ, "OTG_AUDIT_OUTPUT": str(tmp_path), "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_request_obligations_and_four_independent_mutants(tmp_path):
    audit("contract_case_audit.py", tmp_path)
    result = json.loads((tmp_path / "audit-result.json").read_text(encoding="utf-8"))
    assert len(result["obligations"]) == 104
    assert all(c["covered"] for c in result["obligations"]), [
        c for c in result["obligations"] if not c["covered"]
    ]
    assert result["label_mismatches"] == []
    assert all(r["verdict"] == "OK" for r in result["http_results"])
    assert len(result["mutants"]) == 4
    assert all(
        m["strict_status"] == 400 and m["faulty_status"] == 200 and m["detected"]
        for m in result["mutants"]
    )
    assert all(c["covered"] for c in result["measure_checks"])


def test_response_contracts_and_measurement_api_mutants(tmp_path):
    audit("contract_response_audit.py", tmp_path)
    result = json.loads((tmp_path / "extra-audit-result.json").read_text(encoding="utf-8"))
    assert len(result["response_checks"]) == 47
    assert all(c["correct"] for c in result["response_checks"])
    strict, *mutants = result["measure_http"]
    assert strict["mode"] == "strict" and strict["failures"] == []
    assert len(mutants) == 3
    assert all(
        m["witness_status"] == {"strict": 400, "faulty": 200} and m["failures"]
        for m in mutants
    )
    coverage = result["auth_inventory"]["coverage"]
    for credential in ("first", "second"):
        rows = [r for r in coverage if r["field"].endswith("/" + credential)]
        assert {r["keyword"] for r in rows} >= {"単独欠落", "単独無効"}
        assert all(r["status"] == "未生成" for r in rows)
