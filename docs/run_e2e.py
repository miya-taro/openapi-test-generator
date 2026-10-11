#!/usr/bin/env python3
"""docs/ 配下のサンプル一式（openapi.json / mock_api.py / scenarios.yaml）を使い、
Layer 1（生成→実行の配線）と Layer 2（DBシナリオ）を実際にエンドツーエンドで検証する。

事前に PostgreSQL が起動していて docs/apply_schema.py でスキーマが適用済みであることが
前提。CIと scripts/verify_all.py の両方から呼び出せる。

Layer 1 は「--no-abnormal」（正常系のみ）で実行する。mock_api.py はリクエストの
バリデーションを実装していない簡易実装のため、異常系（400 等を期待するケース）を
含めると「モックが検証しないだけ」のNGでノイズになる。ここでの目的はバリデーション
網羅性の確認ではなく、生成〜HTTP実行〜Excel書き出しの配線が壊れていないことの
スモークテスト。Layer 1 の対象はDBデータに依存しない操作に絞る。異常値・制約網羅は
独立した docs/run_validation_e2e.py が担当し、CRUDのDB反映はLayer 2が担当する。
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DEFAULT_SMOKE_OPERATIONS = (
    "healthCheck,login,logout,listUsers,listCategories,listProducts,listOrders,listReviews,"
    "listUserOrders,listOrderItems,getCart"
)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as resp:
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="mock API base URL; defaults to a free loopback port")
    parser.add_argument("--config", type=Path, default=DOCS / "config.json", help="DB config JSON")
    parser.add_argument("--output-dir", type=Path, default=DOCS, help="directory for generated E2E files")
    parser.add_argument(
        "--operations",
        default=DEFAULT_SMOKE_OPERATIONS,
        help="operationId values for the HTTP smoke run (comma-separated)",
    )
    parser.add_argument(
        "--reset-db-between-layers",
        action="store_true",
        help="recreate the sample schema after HTTP smoke cases and before DB scenarios",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_url = args.base_url or f"http://127.0.0.1:{_free_port()}"

    mock_proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "docs.mock_api:app", "--host", "127.0.0.1",
            "--log-level", "error",
            "--port", base_url.rsplit(":", 1)[-1],
        ],
        cwd=str(ROOT),
    )
    try:
        _wait_for_health(base_url)

        # ---------- Layer 1: 生成 → 実行のスモークテスト ----------
        spec_path = args.output_dir / "test_spec.xlsx"
        cases_path = args.output_dir / "test_cases.json"
        result_path = args.output_dir / "test_spec_result.xlsx"

        if _run([
            sys.executable, "src/cli.py", str(DOCS / "openapi.json"),
            "-o", str(cases_path), "--excel-output", str(spec_path),
            "--no-abnormal", "--operations", args.operations,
        ]) != 0:
            print("[e2e][FAIL] Layer1 生成に失敗しました", file=sys.stderr)
            return 1

        # runner.py の終了コードは 1=NG（実失敗）, 2=WARNのみ（応答時間超過等、実失敗はゼロ）。
        # ここでの目的はバリデーション網羅性ではなく配線が壊れていないことの確認なので、
        # WARNのみ（実際には何も失敗していない）を実失敗と同じ扱いにしない
        # （以前は != 0 で両方を一律FAIL扱いしており、WARNだけのケースを誤って
        # 「Layer1 実行が失敗しました」と報告していた）。
        run_code = _run([
            sys.executable, "runner/runner.py", str(spec_path), str(DOCS / "openapi.json"),
            "--base-url", base_url, "--output", str(result_path), "--config", str(args.config),
            "--skip-health-check",
        ])
        if run_code == 1:
            print("[e2e][FAIL] Layer1 実行が失敗しました", file=sys.stderr)
            return 1
        if run_code == 2:
            print("[e2e][WARN] Layer1 実行でWARNが発生しました（実失敗はありません）")
        print("[e2e][OK] Layer1（正常系スモークテスト）")

        # ---------- Layer 2: DBシナリオ検証 ----------
        if args.reset_db_between_layers:
            if _run([sys.executable, "docs/apply_schema.py", "--config", str(args.config)]) != 0:
                print("[e2e][FAIL] Layer2用DBの初期化に失敗しました", file=sys.stderr)
                return 1

        if _run([
            sys.executable, "runner/db_scenario_runner.py",
            str(DOCS / "scenarios.yaml"), str(DOCS / "openapi.json"),
            "--base-url", base_url, "--config", str(args.config),
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
