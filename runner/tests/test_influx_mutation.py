from unittest.mock import Mock

import pytest

from db_backends import influx_mutation as backend
from db_scenario import _parse_scenario
from src.influx_mutation import validate_mutation, fixture_timestamp

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


@pytest.mark.parametrize('fixture', [None, {}, {'fields': {}}, {'fields': {'time': {'type': 'float', 'value': 1}}},
    {'fields': {'value': {'type': 'integer', 'value': True}}}, {'fields': {'value': {'type': 'float', 'value': '1'}}},
    {'fields': {'value': {'type': 'float', 'value': float('inf')}}}, {'fields': {'value': {'type': 'integer', 'value': 2**63}}}])
def test_invalid_fixture_rejected(fixture):
    with pytest.raises(ValueError):
        validate_mutation({**CHECK, 'fixture': fixture})


def test_fixture_changes_review_identity():
    raw = {'name': 'update', 'request': {'operationId': 'update'}, 'influx_mutation': CHECK}
    before = _parse_scenario(raw, {})
    after = _parse_scenario({**raw, 'influx_mutation': {**CHECK, 'fixture': {'fields': {'value': {'type': 'float', 'value': 1}}}}}, {})
    assert before.case_id != after.case_id


def test_fixture_time_retains_nanoseconds_and_rejects_precision_loss():
    assert fixture_timestamp('1970-01-01T00:00:00.000000001Z') == 1
    assert fixture_timestamp('1970-01-01T09:00:00.000000001+09:00') == 1
    assert fixture_timestamp('1969-12-31T23:59:59.999999999Z') == -1
    with pytest.raises(ValueError):
        fixture_timestamp('2026-01-01T00:00:00.0000000001Z')
    with pytest.raises(ValueError):
        fixture_timestamp('2026-01-01T00:00:00.12345678900000000000000000000000001Z')
    with pytest.raises(ValueError):
        fixture_timestamp('9999-01-01T00:00:00Z')


@pytest.mark.parametrize('failure', ['api', 'write_ack', 'cleanup'])
def test_fixture_cleanup_on_api_error_or_uncertain_seed_write(monkeypatch, failure):
    import requests
    import db_scenario_runner as runner
    check = {**CHECK, 'fixture': {'fields': {'value': {'type': 'float', 'value': 1}}}}
    scenario = _parse_scenario({'name': 'update', 'request': {'operationId': 'update'}, 'influx_mutation': check}, {})
    spec = {'paths': {'/point': {'put': {'operationId': 'update'}}}}
    def begin(_check, _config, state):
        state.update(armed=True, cleanup_status='未実施')
        if failure == 'write_ack': raise OSError('reply lost')
    monkeypatch.setattr(backend, 'begin_fixture', begin)
    monkeypatch.setattr(backend, 'prepare', lambda *_: {})
    cleanup = Mock(side_effect=OSError('cleanup lost') if failure == 'cleanup' else None)
    monkeypatch.setattr(backend, 'cleanup_fixture', cleanup)
    monkeypatch.setattr(backend, 'verify', lambda *_: (True, ''))
    monkeypatch.setattr(runner, '_verify_response_contract', lambda *_: ('OK', '', '{}'))
    call = Mock(return_value=(200, {}, None) if failure == 'cleanup' else (0, {}, 'connection lost'))
    monkeypatch.setattr(runner, '_call_api', call)
    evidence = {}
    result = runner._run_scenario(scenario, spec, 'http://localhost', {'influxdb': {'host': 'localhost', 'port': 8086, 'database': 'test'}}, {}, requests.Session(), evidence=evidence)
    assert result[0] is False
    cleanup.assert_called_once()
    assert call.call_count == (0 if failure == 'write_ack' else 1)
    if failure == 'cleanup':
        assert evidence['influx_fixture']['cleanup_status'] == 'NG'
        assert result[4] and '後片付け' in result[1]
