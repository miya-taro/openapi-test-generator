#!/usr/bin/env python3
"""docs/openapi.json + docs/mock_api.py に対して schemathesis を実行する。

openapi-test-run（runner.py）のLayer1は「決定論的・レビュー可能な既知の観点」を
検証する回帰スイートだが、こちらは hypothesis ベースのランダム生成で
「人間が境界値として想定していない組み合わせ」を継続的に探索する補助レーンとして
別ジョブで並走させる（詳細は設計検討の議論を参照）。

役割が異なるため、ここでの失敗はCIをブロックしない
（決定論的な回帰スイートの合否ゲートとは別に、証跡としてJUnit XML/カセットを残すのみ）。
mock_api.py はリクエストのバリデーションを実装していない簡易実装のため、
契約違反そのものではなく明確なサーバークラッシュ（500エラー）のみを検出対象にする。

CI（.github/workflows/test.yml の e2e ジョブ）専用。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PORT = 8081
BASE_URL = f"http://127.0.0.1:{PORT}"
HEALTH_URL = f"{BASE_URL}/health"

# 実行するたびに探索するケースが変わらないよう固定する（再現性のため）。
SEED = 20260825
MAX_EXAMPLES = 10


def _wait_for_health(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=2) as resp:
                if resp.status == 200:
                    print("[schemathesis] mock API is healthy")
                    return
        except (urllib.error.URLError, OSError) as e:
            last_error = e
        time.sleep(1)
    raise RuntimeError(f"mock API did not become healthy within {timeout}s: {last_error}")


def main() -> int:
    mock_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "docs.mock_api:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT),
    )
    try:
        _wait_for_health()

        junit_path = DOCS / "_ci_schemathesis_result.xml"
        cassette_path = DOCS / "_ci_schemathesis_cassette.yaml"

        cmd = [
            "schemathesis", "run", str(DOCS / "openapi.json"),
            "-u", BASE_URL,
            f"--seed={SEED}",
            "-n", str(MAX_EXAMPLES),
            "-c", "not_a_server_error",
            "--report", "junit,vcr",
            "--report-junit-path", str(junit_path),
            "--report-vcr-path", str(cassette_path),
            "--generation-database", "none",
        ]
        print(f"[schemathesis] $ {' '.join(cmd)}")
        # Windows既定コンソール(cp932)では schemathesis 自身の絵文字付き進捗表示が
        # UnicodeEncodeError でクラッシュするため、UTF-8 を強制する。
        env = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(cmd, cwd=str(ROOT), env=env)

        # 探索的なファジングであり、決定論的な回帰スイート（Layer1）とは役割が異なるため、
        # ここでの失敗はCI全体をブロックしない。証跡（JUnit XML・カセット）を残すことが目的。
        if result.returncode != 0:
            print(
                f"[schemathesis][WARN] NGを検出しました（このジョブはブロックしません）。"
                f"詳細: {junit_path}"
            )
        else:
            print("[schemathesis][OK] 検出されたNGはありませんでした")
        return 0
    finally:
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            mock_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
