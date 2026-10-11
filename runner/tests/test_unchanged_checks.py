"""Snapshot scopes are explicit, bounded and included in the reviewable case definition."""
import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from db_scenario import parse_scenarios, ScenarioError
from db_backends.postgres_backend import unchanged_rows

RAW = {"name": "error has no side effects", "request": {"operationId": "update", "body": {"id": "bad"}},
       "response_check": {"expect": {"status": 422}},
       "db_unchanged": [{"table": "users", "columns": ["id", "name"], "where": {"site_id": 1}}]}


def test_scope_is_preserved_and_changing_it_invalidates_case_review():
    scenario = parse_scenarios(json.dumps({"scenarios": [RAW]}))[0]
    assert scenario.case_definition()["dbUnchanged"] == RAW["db_unchanged"]
    other = copy.deepcopy(RAW)
    other["db_unchanged"][0]["columns"].append("email")
    assert parse_scenarios(json.dumps({"scenarios": [other]}))[0].case_id != scenario.case_id


@pytest.mark.parametrize("scope", [[], [{}], [{"table": "users; DROP TABLE users", "columns": ["id"]}],
                                   [{"table": "users", "columns": ["id", "id"]}],
                                   [{"table": "users", "columns": ["id"], "where": {"id": [1]}}]])
def test_invalid_scope_is_rejected(scope):
    with pytest.raises(ScenarioError):
        parse_scenarios(json.dumps({"scenarios": [{**RAW, "db_unchanged": scope}]}))


def test_snapshot_comparison_checks_types_multiplicity_and_values_ignoring_order():
    before = [{"id": 1, "v": {"nested": [Decimal("1.00"), True]}}, {"id": 2, "v": None}]
    assert unchanged_rows(before, list(reversed(before)))
    assert not unchanged_rows(before, [before[0], before[0]])
    assert not unchanged_rows(before, before + [before[0]])
    assert not unchanged_rows(before, [{"id": 1, "v": {"nested": ["1.00", True]}}, before[1]])
    assert not unchanged_rows(before, [{"id": 1, "v": {"nested": [Decimal("1.00"), 1]}}, before[1]])
