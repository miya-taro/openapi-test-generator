from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import TextIO


@dataclass(frozen=True)
class WorkflowEvent:
    type: str
    stage: str | None = None
    status: str | None = None
    level: str | None = None
    message: str | None = None
    detail: str | None = None
    current: int | None = None
    total: int | None = None
    exit_code: int | None = None
    kind: str | None = None
    path: str | None = None

    @classmethod
    def log(cls, stage: str, message: str, level: str = "info") -> WorkflowEvent:
        return cls(type="log", stage=stage, level=level, message=message)

    @classmethod
    def workflow_finished(cls, status: str, exit_code: int) -> WorkflowEvent:
        return cls(type="workflow_finished", status=status, exit_code=exit_code)

    def to_dict(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def emit_event(event: WorkflowEvent, stream: TextIO) -> None:
    stream.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    stream.flush()

