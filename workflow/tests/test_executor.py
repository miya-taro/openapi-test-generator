import os
import subprocess
import sys
from unittest.mock import Mock

from workflow.executor import run_command


def test_run_command_wraps_child_output_as_log_events():
    emitted = []
    command = [sys.executable, "-c", "print('line 1'); print('line 2')"]

    result = run_command("generate", command, emitted.append)

    assert [event.message for event in emitted if event.type == "log"] == [
        "line 1",
        "line 2",
    ]
    assert result.status == "passed"
    assert emitted[0].type == "stage_started"
    assert emitted[-1].type == "stage_finished"


def test_run_command_reports_launch_failure_without_raw_traceback(monkeypatch):
    emitted = []
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("python missing")))

    result = run_command("generate", ["python", "missing.py"], emitted.append)

    assert result.status == "error"
    assert result.exit_code == -1
    assert emitted[-1].type == "stage_finished"
    assert emitted[-1].message == (
        "処理を開始できませんでした。Pythonの実行環境を確認してください。"
    )
    assert "python missing" in emitted[-1].detail


def test_run_command_maps_known_progress_line():
    emitted = []
    command = [
        sys.executable,
        "-c",
        "print('[OK] TC-001 (3/10)')",
    ]

    run_command("execute", command, emitted.append)

    progress = [event for event in emitted if event.type == "progress"]
    assert len(progress) == 1
    assert progress[0].current == 3
    assert progress[0].total == 10


def test_nonzero_exit_code_is_failed_stage():
    emitted = []
    command = [sys.executable, "-c", "raise SystemExit(2)"]

    result = run_command("execute", command, emitted.append)

    assert result.status == "warning"
    assert result.exit_code == 2


def test_exit_code_two_can_be_treated_as_failure_for_other_runners():
    emitted = []
    command = [sys.executable, "-c", "raise SystemExit(2)"]

    result = run_command("explore", command, emitted.append, warning_exit_codes=())

    assert result.status == "failed"
    assert result.exit_code == 2
    assert emitted[-1].status == "failed"


def test_child_environment_values_are_redacted_from_streamed_output():
    emitted = []
    token = "test-token-987"
    command = [
        sys.executable,
        "-c",
        "import os; print(os.environ['API_TESTER_TOKEN']); raise SystemExit(2)",
    ]
    result = run_command(
        "explore", command, emitted.append,
        env={**os.environ, "API_TESTER_TOKEN": token},
        warning_exit_codes=(),
        redact_values=(token,),
    )

    output = "\n".join(event.message or "" for event in emitted)
    assert token not in output
    assert "[REDACTED]" in output
    assert result.status == "failed"
