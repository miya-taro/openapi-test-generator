import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]))
from models import RunCase, RunResult
from response_schema import from_run_case
from verifier import verify


@pytest.mark.parametrize('code', [200, 201, 204, 400, 401, 404, 500])
@pytest.mark.parametrize('body', ['', '{}', 'null', ' ', '\n', 'unexpected'])
def test_no_content_response_requires_exactly_empty_body(code, body):
    spec = {'paths': {'/set': {'post': {'operationId': 'set', 'responses': {str(code): {'description': 'no body'}}}}}}
    case = RunCase('id', 'set', '/set', 'POST', 'body', 'body', '', str(code), '', '', '', '')
    schema = from_run_case(case, spec)
    result = RunResult(case, code, body, {}, 0, 0)
    assert (verify(result, schema)[0] == 'OK') is (body == '')


def test_undocumented_body_is_not_confused_with_empty_json_schema():
    spec = {'paths': {'/set': {'post': {'operationId': 'set', 'responses': {'200': {'description': 'any JSON', 'content': {'application/json': {'schema': {}}}}}}}}}
    case = RunCase('id', 'set', '/set', 'POST', 'body', 'body', '', '200', '', '', '', '')
    assert verify(RunResult(case, 200, '{}', {'Content-Type': 'application/json'}, 0, 0), from_run_case(case, spec))[0] == 'OK'
