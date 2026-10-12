import copy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import sys
from pathlib import Path

import pytest
import yaml

sys.path[:0] = [str(Path(__file__).parents[1]), str(Path(__file__).parents[2])]
from db_backends import postgres_insert as pg
from db_scenario import parse_scenarios, ScenarioError
from src.insert_mapping import validate_insert


def definition():
    return {'table': 'h_plan', 'primary_key': ['datetime', 'created', 'site_id', 'use_id'], 'rows_path': 'plans[].controls[]', 'columns': {
        'datetime': {'kind': 'datetime', 'date': 'plans[].date', 'time': 'plans[].controls[].time', 'timezone': 'Asia/Tokyo'},
        'created': {'kind': 'runtime', 'tolerance_seconds': 2}, 'site_id': {'kind': 'request', 'path': 'site_id'},
        'use_id': {'kind': 'request', 'path': 'type'}, 'profit': {'kind': 'request', 'path': 'plans[].profit'},
        'buy': {'kind': 'request', 'path': 'plans[].controls[].buy'},
        'correct_point': {'kind': 'request', 'path': 'plans[].controls[].correct_point', 'missing': 'null'},
        'fixed': {'kind': 'fixed', 'value': False}, 'force': {'kind': 'request', 'path': 'force'}}}


def body():
    return {'site_id': 101, 'type': '1-1', 'force': False, 'plans': [
        {'date': '2026-10-12T00:00:00+09:00', 'profit': 10, 'controls': [{'time': '10:00:00', 'buy': 0.125, 'correct_point': {'start': {'buy': 1}}}, {'time': '11:00:00', 'buy': 2}]},
        {'date': '2026-10-13T00:00:00+09:00', 'profit': 20, 'controls': [{'time': '00:00:00', 'buy': 3}]}]}


def test_nested_rows_parent_json_and_timezone():
    request = body()
    before = copy.deepcopy(request)
    rows = pg.expected_rows(definition(), request, {}, [])
    assert len(rows) == 3 and [r['profit'] for r in rows] == [10, 10, 20]
    assert rows[2]['datetime'] == datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    assert rows[0]['correct_point'] == {'start': {'buy': 1}}
    assert rows[1]['correct_point'] is None
    assert all(r['use_id'] == '1-1' and r['force'] is False and r['fixed'] is False for r in rows)
    assert request == before


def test_site_precedence_and_lookup_are_explicit(monkeypatch):
    check = definition()
    check['columns']['site_id'] = {'kind': 'lookup', 'path': 'location_id', 'preferred_path': 'site_id', 'lookup': {
        'engine': 'postgres', 'table': 't_site', 'match_column': 'location_id', 'value_column': 'site_id',
        'cardinality': 'one', 'on_empty': 'unverified', 'value_type': 'integer'}}
    request = body(); request['location_id'] = 'OTHER'
    monkeypatch.setattr(pg.lookup_response, '_read_values', lambda *args: pytest.fail('site_id must take precedence'))
    assert all(r['site_id'] == 101 for r in pg.expected_rows(check, request, {}, []))
    del request['site_id']
    calls = []
    def read(*args):
        calls.append(args[-1]); return [202]
    monkeypatch.setattr(pg.lookup_response, '_read_values', read)
    assert all(r['site_id'] == 202 for r in pg.expected_rows(check, request, {}, []))
    assert calls == ['OTHER']
    monkeypatch.setattr(pg.lookup_response, '_read_values', lambda *args: [101, 202])
    with pytest.raises(pg.DBResponseCheckUnverified):
        pg.expected_rows(check, request, {}, [])


@pytest.mark.parametrize('fault', ['none', 'missing', 'extra', 'duplicate', 'wrong_value', 'wrong_parent', 'wrong_json', 'old_created', 'modified_old', 'deleted_old', 'old_only'])
def test_difference_rejects_bad_inserts_and_reused_old_rows(fault):
    check = definition(); expected = pg.expected_rows(check, body(), {}, [])
    now = datetime.now(timezone.utc)
    old = [{**expected[0], 'created': now - timedelta(days=1)}]
    added = [{**r, 'created': now} for r in copy.deepcopy(expected)]
    added[0]['buy'] = Decimal('0.125')
    after = copy.deepcopy(old) + added
    if fault == 'missing': after.pop()
    if fault == 'extra': after.append({**added[0], 'site_id': 909})
    if fault == 'duplicate': after.append({**added[0], 'created': now + timedelta(milliseconds=1)})
    if fault == 'wrong_value': after[1]['buy'] = Decimal('0.126')
    if fault == 'wrong_parent': after[-1]['profit'] = 10
    if fault == 'wrong_json': after[1]['correct_point']['start']['buy'] = 9
    if fault == 'old_created': after[1]['created'] = now - timedelta(hours=1)
    if fault == 'modified_old': after[0]['buy'] = 999
    if fault == 'deleted_old': after.pop(0)
    if fault == 'old_only': after = old
    evidence = {}
    ok, _ = pg.compare(check, old, after, expected, now, now, evidence)
    assert ok is (fault == 'none')
    assert evidence['verdict'] == ('OK' if ok else 'NG')


@pytest.mark.parametrize('change', [lambda c: c.update(rows_path='other[].rows[]'),
    lambda c: c['columns']['buy'].update(path='unrelated[].buy'),
    lambda c: c['columns']['created'].update(tolerance_seconds=-1),
    lambda c: c['columns']['datetime'].update(timezone='unknown'),
    lambda c: c.update(primary_key=['unmapped']), lambda c: c.update(table='h_plan;DROP TABLE h_plan')])
def test_bad_mappings_are_rejected(change):
    check = definition(); change(check)
    with pytest.raises(ValueError): validate_insert(check)


def test_no_implicit_rounding_bool_number_coercion_or_ambiguous_time():
    assert not pg.equal(Decimal('1.235'), 1.2345)
    assert not pg.equal(True, 1)
    assert pg.equal({'a': [Decimal('0.1')]}, {'a': [0.1]})
    for day, clock in [('2026-03-08', '02:30:00'), ('2026-11-01', '01:30:00')]:
        with pytest.raises(ValueError, match='夏時間'):
            pg.combined_datetime(day, clock, 'America/New_York')


def test_case_identity_includes_mapping_and_empty_body():
    raw = {'name': 'insert', 'request': {'operationId': 'set'}, 'db_insert_check': definition(), 'response_check': {'expect': {'status': 200, 'empty_body': True}}}
    case = parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))[0]
    assert case.case_definition()['dbInsertCheck'] == definition()
    original = case.case_id
    case.db_insert_check['columns']['fixed']['value'] = True
    assert original != case.case_id
    raw['response_check']['expect']['empty_body'] = 'yes'
    with pytest.raises(ScenarioError): parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))
