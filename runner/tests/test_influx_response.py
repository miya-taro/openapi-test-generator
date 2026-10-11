"""Fail-closed checks for InfluxQL scopes, bounds and typed timestamp comparison."""
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest

from db_backends import influx_response as backend
from db_scenario import DBResponseCheck, DBResponseFilter, DBUnchangedCheck, _parse_scenario
from response_check import check_db_rows
from src.db_scope import validate_scopes

CONFIG = {'host': 'localhost', 'port': 8086, 'database': 'measurements'}
SCOPE = DBUnchangedCheck('measure', ['time', 'item', 'value'], engine='influxdb',
                        time_start='2026-01-01T00:00:00Z', time_end='2026-01-01T01:00:00Z')


def result(points):
    response = Mock()
    response.get_points.return_value = iter(points)
    return response


def client_results(points):
    client = Mock()
    client.query.side_effect = [result([{'fieldKey': 'value'}]), result([{'tagKey': 'item'}]), result(points)]
    return client


@pytest.mark.parametrize('change', [
    {'engine': 'mysql'}, {'time_start': '2026-01-01'}, {'time_end': None},
    {'time_start': '2026-01-02T00:00:00Z'}, {'where': {'item': None}},
    {'columns': ['value; DROP DATABASE x']}, {'where': {'value': float('nan')}},
])
def test_reject_invalid_scope(change):
    with pytest.raises(ValueError):
        validate_scopes([{**asdict(SCOPE), **change}])


def test_scope_period_keeps_nanosecond_order():
    with pytest.raises(ValueError, match='開始'):
        validate_scopes([{**asdict(SCOPE), 'time_start': '2026-01-01T00:00:00.000000002Z',
                          'time_end': '2026-01-01T00:00:00.000000001Z'}])


def test_snapshot_reads_fixed_range_and_requested_columns():
    client = client_results([{'time': '2026-01-01T00:00:00Z', 'item': 'a', 'value': 2, 'extra': 'ignored'}])
    with patch.object(backend, 'InfluxDBClient', return_value=client):
        rows = backend.snapshot_rows(CONFIG, SCOPE)
    assert rows == [{'time': '2026-01-01T00:00:00Z', 'item': 'a', 'value': 2}]
    query = client.query.call_args.args[0]
    assert "now()" not in query
    assert '"time" >=' in query and '"time" <=' in query
    client.close.assert_called_once()


def test_unknown_column_fails_even_when_range_empty():
    client = client_results([])
    scope = DBUnchangedCheck(**{**asdict(SCOPE), 'columns': ['missing']})
    with patch.object(backend, 'InfluxDBClient', return_value=client), pytest.raises(backend.DBResponseCheckError):
        backend.snapshot_rows(CONFIG, scope)
    assert client.query.call_count == 2
    client.close.assert_called_once()


def test_too_many_points_cannot_be_truncated_into_pass(monkeypatch):
    monkeypatch.setattr(backend, 'MAX_POINTS', 2)
    client = client_results([{'time': '2026-01-01T00:00:00Z', 'item': 'a', 'value': 2}] * 3)
    with patch.object(backend, 'InfluxDBClient', return_value=client), pytest.raises(backend.DBResponseCheckUnverified):
        backend.snapshot_rows(CONFIG, SCOPE)
    client.close.assert_called_once()


def test_literals_escaped_and_identifiers_rejected():
    clause = backend._clause(('item', 'in', ["a' OR true", 'b\\c']))
    assert "a\\' OR true" in clause and 'b\\\\c' in clause
    with pytest.raises(ValueError):
        backend._clause(('item; DROP', '=', 'x'))
    for value in [None, {}, float('inf')]:
        with pytest.raises(backend.DBResponseCheckError):
            backend._clause(('value', '=', value))


def test_influx_time_compares_instant_without_losing_nanoseconds():
    check = DBResponseCheck('m', {'time': 'time'}, engine='influxdb')
    rows = [{'time': backend.InfluxTimestamp('2026-01-01T00:00:00.000000001Z')}]
    assert check_db_rows(check, [{'time': '2026-01-01T09:00:00.000000001+09:00'}], rows)[0]
    assert not check_db_rows(check, [{'time': '2026-01-01T00:00:00.000000002Z'}], rows)[0]
    assert not check_db_rows(check, [{'time': '2026-01-01T00:00:00Z'}], rows)[0]


def test_engine_and_scope_are_part_of_review_case_identity():
    base = {'name': 'influx', 'request': {'operationId': 'get'},
            'db_response_check': {'table': 'm', 'fields': {'value': 'value'}, 'engine': 'influxdb'}}
    scenario = _parse_scenario(base, {})
    other = _parse_scenario({**base, 'db_response_check': {**base['db_response_check'], 'engine': 'postgres'}}, {})
    assert scenario.case_id != other.case_id
    assert scenario.case_definition()['dbResponseCheck']['engine'] == 'influxdb'


def test_connection_closed_on_query_failure():
    client = Mock()
    client.query.side_effect = RuntimeError('connection failed')
    with patch.object(backend, 'InfluxDBClient', return_value=client), pytest.raises(RuntimeError):
        backend.prepare_db_response_check(DBResponseCheck('m', {'value': 'value'}, engine='influxdb'), CONFIG, {}, {})
    client.close.assert_called_once()


def test_missing_fixed_query_is_unverified_before_connect():
    check = DBResponseCheck('m', {'value': 'value'}, [DBResponseFilter('query', 'site', 'site', '=', False)], engine='influxdb')
    with patch.object(backend, 'InfluxDBClient') as client, pytest.raises(backend.DBResponseCheckUnverified):
        backend.prepare_db_response_check(check, CONFIG, {}, {})
    client.assert_not_called()
