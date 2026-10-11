from unittest.mock import Mock

import pytest

from db_backends import influx_mutation as backend
from db_scenario import _parse_scenario
from src.influx_mutation import validate_mutation

CHECK = {'action': 'update', 'measurement': 'measure', 'time': '2026-01-01T00:00:00Z',
         'tags': {'item': 'a'}, 'fields': {'value': 2.0}, 'preserve_unmapped': True}


@pytest.mark.parametrize('change', [{'action': 'upsert'}, {'measurement': 'm;DROP'}, {'time': '2026-01-01'},
                                    {'tags': {'item': 1}}, {'fields': {'value': None}}, {'fields': {}},
                                    {'fields': {'time': 1}}, {'fields': {'item': 'a'}}, {'fields': {'value': float('nan')}},
                                    {'action': 'delete'}, {'preserve_unmapped': 'true'}])
def test_invalid_definition_rejected(change):
    with pytest.raises(ValueError):
        validate_mutation({**CHECK, **change})


@pytest.mark.parametrize('action,rows', [('insert', [{'value': 1}]), ('update', []), ('delete', []), ('update', [{'value': 2.0}])])
def test_preconditions_do_not_create_false_passes(monkeypatch, action, rows):
    monkeypatch.setattr(backend, '_points', Mock(return_value=rows))
    with pytest.raises(backend.DBResponseCheckUnverified):
        backend.prepare({**CHECK, 'action': action}, {})


@pytest.mark.parametrize('after,passed', [([{'value': 2.0, 'untouched': 7}], True),
                                         ([{'value': 2.0, 'untouched': 8}], False),
                                         ([{'value': 2.0}], False), ([{'value': True, 'untouched': 7}], False),
                                         ([], False)])
def test_update_preserves_only_explicitly_selected_semantics(monkeypatch, after, passed):
    monkeypatch.setattr(backend, '_points', Mock(return_value=after))
    evidence = {'before_points': [{'value': 1.0, 'untouched': 7}]}
    ok, _ = backend.verify(CHECK, {}, evidence)
    assert ok is passed
    assert evidence['verdict'] == ('OK' if passed else 'NG')


def test_definition_part_of_review_identity():
    raw = {'name': 'mutation', 'request': {'operationId': 'update'}, 'influx_mutation': CHECK}
    first = _parse_scenario(raw, {})
    second = _parse_scenario({**raw, 'influx_mutation': {**CHECK, 'fields': {'value': 3.0}}}, {})
    assert first.case_definition()['influxMutation'] == CHECK
    assert first.case_id != second.case_id
