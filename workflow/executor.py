from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from workflow.events import WorkflowEvent


_PROGRESS = re.compile(r"\((?P<current>\d+)\s*/\s*(?P<total>\d+)\)")
EventSink = Callable[[WorkflowEvent], None]


@dataclass(frozen=True)
class StageResult:
    status: str
    exit_code: int

    @classmethod
    def passed(cls) -> StageResult:
        return cls(status="passed", exit_code=0)

    @classmethod
    def failed(cls, exit_code: int = 1) -> StageResult:
        return cls(status="failed", exit_code=exit_code)


def _status_for_exit_code(exit_code: int, warning_exit_codes: Sequence[int] = (2,)) -> str:
    if exit_code == 0:
        return "passed"
    if exit_code in warning_exit_codes:
        return "warning"
    return "failed"


def _output_event(stage: str, line: str) -> WorkflowEvent:
    match = _PROGRESS.search(line)
    if match:
        return WorkflowEvent(
            type="progress",
            stage=stage,
            current=int(match.group("current")),
            total=int(match.group("total")),
            message=line,
        )
    level = "error" if "[ERROR]" in line else "warning" if "[WARN]" in line else "info"
    return WorkflowEvent.log(stage, line, level=level)


def run_command(
    stage: str,
    command: Sequence[str],
    emit: EventSink,
    *,
    env: Mapping[str, str] | None = None,
    warning_exit_codes: Sequence[int] = (2,),
    redact_values: Sequence[str] = (),
) -> StageResult:
    emit(
        WorkflowEvent(
            type="stage_started",
            stage=stage,
            status="running",
            message=f"{stage} を開始しました",
        )
    )
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            env=dict(env) if env is not None else None,
        )
    except OSError as exc:
        message = "処理を開始できませんでした。Pythonの実行環境を確認してください。"
        emit(
            WorkflowEvent(
                type="stage_finished",
                stage=stage,
                status="error",
                message=message,
                detail=str(exc),
                exit_code=-1,
            )
        )
        return StageResult(status="error", exit_code=-1)

    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            for secret in redact_values:
                if secret:
                    line = line.replace(secret, "[REDACTED]")
            if line:
                emit(_output_event(stage, line))
    exit_code = process.wait()
    status = _status_for_exit_code(exit_code, warning_exit_codes)
    emit(
        WorkflowEvent(
            type="stage_finished",
            stage=stage,
            status=status,
            exit_code=exit_code,
        )
    )
    return StageResult(status=status, exit_code=exit_code)
