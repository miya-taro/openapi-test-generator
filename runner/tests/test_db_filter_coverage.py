"""Read-only witness checks must not overstate body, OR or IN coverage."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from db_backends import postgres_backend as pg
from db_scenario import DBResponseFilter


def filter_(name, column, operator, group=None):
    return DBResponseFilter("body", name, column, operator, False, None, group)


def cursor(more=True, witness=True):
    cur = MagicMock()
    cur.fetchall.return_value = [{"id": 1}, {"id": 2}] if more else [{"id": 1}]
    cur.fetchone.return_value = {"id": 1} if witness else None
    return cur


def test_each_and_condition_must_have_distinguishing_data():
    filters = [filter_("site_id", "site", "="), filter_("start", "time", ">=")]
    specs = [("site", "=", 1, None), ("time", ">=", "2026-01-01", None)]
    cur = cursor()
    cur.fetchall.side_effect = [[{}, {}], [{}]]
    with pytest.raises(pg.DBResponseCheckUnverified, match="body.start.*省略"):
        pg._prove_filter_coverage(cur, '"measurements"', filters, specs, 1)


def test_missing_boundary_is_unverified():
    cur = cursor(witness=False)
    with pytest.raises(pg.DBResponseCheckUnverified, match="境界値"):
        pg._prove_filter_coverage(cur, '"measurements"', [filter_("end", "time", "<")],
                                  [("time", "<", "2026-01-03", None)], 1)


def test_or_group_is_removed_as_a_unit_then_each_branch_is_proven():
    filters = [filter_("site", "site", "=", "A"), filter_("location", "location", "=", "A")]
    specs = [("site", "=", 1, "A"), ("location", "=", "B", "A")]
    cur = cursor()
    coverage = pg._prove_filter_coverage(cur, '"measurements"', filters, specs, 1)
    assert cur.fetchall.call_count == 1
    assert cur.fetchone.call_count == 2
    assert all(item["or_branch_detectable"] for item in coverage)
    queries = [call.args for call in cur.execute.call_args_list]
    assert "WHERE" not in queries[0][0]
    assert '("location" = %s) IS NOT TRUE' in queries[1][0]
    assert queries[1][1] == [1, "B"]


def test_or_branch_without_exclusive_witness_is_unverified():
    filters = [filter_("site", "site", "=", "A"), filter_("location", "location", "=", "A")]
    with pytest.raises(pg.DBResponseCheckUnverified, match="OR分岐"):
        pg._prove_filter_coverage(cursor(witness=False), '"measurements"', filters,
                                  [("site", "=", 1, "A"), ("location", "=", "B", "A")], 1)


def test_every_in_member_requires_a_witness_and_values_stay_bound():
    cur = cursor()
    cur.fetchone.side_effect = [{"id": 1}, None]
    with pytest.raises(pg.DBResponseCheckUnverified, match="IN指定値"):
        pg._prove_filter_coverage(cur, '"measurements"', [filter_("items", "item", "in")],
                                  [("item", "in", ["temperature", "x' OR true --"], None)], 1)
    assert cur.execute.call_args.args[1] == ["x' OR true --"]
    assert "x' OR" not in cur.execute.call_args.args[0]


def test_empty_filter_list_requires_no_witness():
    cur = cursor()
    assert pg._prove_filter_coverage(cur, '"measurements"', [], [], 0) == []
    cur.execute.assert_not_called()
