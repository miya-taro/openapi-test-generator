import io
import json

from workflow.events import WorkflowEvent, emit_event


def test_emit_event_writes_one_utf8_json_object_per_line():
    stream = io.StringIO()
    emit_event(WorkflowEvent.log("generate", "71件生成しました"), stream)
    assert json.loads(stream.getvalue()) == {
        "type": "log",
        "stage": "generate",
        "level": "info",
        "message": "71件生成しました",
    }
    assert stream.getvalue().endswith("\n")


def test_event_omits_fields_that_are_not_applicable():
    event = WorkflowEvent.workflow_finished("passed", 0)
    assert event.to_dict() == {
        "type": "workflow_finished",
        "status": "passed",
        "exit_code": 0,
    }

