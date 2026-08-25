#!/usr/bin/env python3
"""docs/ 配下のサンプル一式（openapi.json / mock_api.py / scenarios.yaml）を使い、
Layer 1（生成→実行の配線）と Layer 2（DBシナリオ）を実際にエンドツーエンドで検証する。

CI（.github/workflows/test.yml の e2e ジョブ）専用。事前に PostgreSQL が起動していて
docs/apply_schema.py でスキーマが適用済みであることが前提。

Layer 1 は「--no-abnormal」（正常系のみ）で実行する。mock_api.py はリクエストの
バリデーションを実装していない簡易実装のため、異常系（400 等を期待するケース）を
含めると「モックが検証しないだけ」のNGでノイズになる。ここでの目的はバリデーション
網羅性の確認ではなく、生成〜HTTP実行〜Excel書き出しの配線が壊れていないことの
スモークテスト。
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
BASE_URL = "http://127.0.0.1:8080"
HEALTH_URL = f"{BASE_URL}/health"


def _wait_for_health(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    print("[e2e] mock API is healthy")
                    return
        except (urllib.error.URLError, OSError) as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(f"mock API did not become healthy within {timeout}s: {last_error}")


def _run(cmd: list[str]) -> int:
    print(f"[e2e] $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    mock_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "docs.mock_api:app", "--host", "127.0.0.1", "--port", "8080"],
        cwd=str(ROOT),
    )
    try:
        _wait_for_health()

        # ---------- Layer 1: 生成 → 実行のスモークテスト ----------
        spec_path = DOCS / "_ci_試験仕様.xlsx"
        cases_path = DOCS / "_ci_test_cases.json"
        result_path = DOCS / "_ci_試験仕様_result.xlsx"

        if _run([
            sys.executable, "src/cli.py", str(DOCS / "openapi.json"),
            "-o", str(cases_path), "--excel-output", str(spec_path),
            "--no-abnormal",
        ]) != 0:
            print("[e2e][FAIL] Layer1 生成に失敗しました", file=sys.stderr)
            return 1

        if _run([
            sys.executable, "runner/runner.py", str(spec_path), str(DOCS / "openapi.json"),
            "--base-url", BASE_URL, "--output", str(result_path),
            "--skip-health-check",
        ]) != 0:
            print("[e2e][FAIL] Layer1 実行が失敗しました", file=sys.stderr)
            return 1
        print("[e2e][OK] Layer1（正常系スモークテスト）")

        # ---------- Layer 2: DBシナリオ検証 ----------
        if _run([
            sys.executable, "runner/db_scenario_runner.py",
            str(DOCS / "scenarios.yaml"), str(DOCS / "openapi.json"),
            "--base-url", BASE_URL, "--config", str(DOCS / "config.json"),
            "--skip-health-check",
        ]) != 0:
            print("[e2e][FAIL] Layer2（DBシナリオ）が失敗しました", file=sys.stderr)
            return 1
        print("[e2e][OK] Layer2（DBシナリオ）")

        return 0
    finally:
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            mock_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
