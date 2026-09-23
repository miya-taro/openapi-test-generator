import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "script",
    ["runner.py", "db_scenario_runner.py"],
)
def test_runner_entrypoints_start_when_python_does_not_add_script_directory(script):
    result = subprocess.run(
        [sys.executable, "-P", str(REPO_ROOT / "runner" / script), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
