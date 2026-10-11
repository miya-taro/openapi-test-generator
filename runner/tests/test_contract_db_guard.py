from unittest.mock import Mock

import pytest

from contract_db_guard import execute_guarded
from db_backends import postgres_backend
from models import RunCase, RunResult
from src.db_scope import KEY, validate_scopes


@pytest.mark.parametrize("status", ["4xx", "400", "401/403"])
@pytest.mark.parametrize("after,changed", [([{"id": 1}], False), ([], True), ([{"id": 2}], True), ([{"id": 1}, {"id": 1}], True)])
def test_guard_checks_every_error_case(monkeypatch, status, after, changed):
    case = RunCase("c", "op", "/x", "GET", "body", "x", "null", status, "", "", "", "")
    api = {"paths": {"/x": {"get": {KEY: [{"table": "data", "columns": ["id"]}]}}}}
    snapshot = Mock(side_effect=[[{"id": 1}], after])
    monkeypatch.setattr(postgres_backend, "snapshot_rows", snapshot)
    send = Mock(return_value=RunResult(case, 400, "{}", {}, 1, 0))
    evidence = []
    result, failures = execute_guarded(case, api, {}, send, evidence)
    assert result.actual_status == 400
    assert bool(failures) == changed
    assert evidence[0]["scopes"][0]["verdict"] == ("NG" if changed else "OK")
    send.assert_called_once()
    assert snapshot.call_count == 2


def test_snapshot_failure_prevents_http_and_is_not_a_pass(monkeypatch):
    case = RunCase("c", "op", "/x", "POST", "body", "x", "null", "4xx", "", "", "", "")
    api = {"paths": {"/x": {"post": {KEY: [{"table": "data", "columns": ["id"]}]}}}}
    monkeypatch.setattr(postgres_backend, "snapshot_rows", Mock(side_effect=ValueError("secret")))
    send = Mock()
    result, failures = execute_guarded(case, api, {}, send, [])
    assert failures and result.exit_code != 0 and "secret" not in result.error
    send.assert_not_called()


@pytest.mark.parametrize("scope", [[{"table": "data; DROP TABLE data", "columns": ["id"]}],
                                  [{"table": "data", "columns": []}],
                                  [{"table": "data", "columns": ["id"], "where": {"id": {"sql": "1"}}}]])
def test_bad_scopes_rejected(scope):
    with pytest.raises(ValueError):
        validate_scopes(scope)
