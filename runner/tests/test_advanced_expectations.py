from copy import deepcopy
from decimal import Decimal

import pytest

from src.ddl_catalog import parse_ddl
from src.expectation_rules import evaluate, validate_rules, equal
from src.influx_bulk import validate_bulk
from db_backends import expectation_rules as backend, influx_bulk
from db_backends.postgres_backend import DBResponseCheckUnverified
from db_scenario import _parse_scenario


def ref(path): return {'ref': path}
def lit(value): return {'literal': value}
def expr(op, *args): return {'op': op, 'args': list(args)}


def test_ddl_constraints_and_alter_without_executing():
    result = parse_ddl('''CREATE TABLE T_SITE (id integer PRIMARY KEY, name text NOT NULL UNIQUE);
      CREATE TABLE reading (site_id integer REFERENCES t_site(id), stamp timestamptz,
        amount numeric(15,3) DEFAULT 0 CHECK(amount >= 0), PRIMARY KEY(site_id,stamp));
      ALTER TABLE reading ADD COLUMN enabled boolean DEFAULT false;
      ALTER TABLE reading ADD CONSTRAINT fk_site FOREIGN KEY(site_id) REFERENCES t_site(id);
      CREATE TABLE other.hidden (id integer); SELECT pg_sleep(100);''')
    sites, readings, hidden = result['tables']
    assert sites['name'] == 't_site'
    assert sites['unique'] == [['name']]
    assert readings['primaryKey'] == ['site_id', 'stamp']
    assert [c['nullable'] for c in readings['columns']][:2] == [False, False]
    assert readings['columns'][2]['default'] == '0'
    assert readings['columns'][-1]['name'] == 'enabled'
    assert len(readings['foreignKeys']) == 2
    assert readings['foreignKeys'][0]['table'] == 'public.t_site'
    assert readings['checks'] and readings['mappingSelectable']
    assert not hidden['mappingSelectable'] and result['warnings']


def test_ddl_unsupported_alter_not_offered_as_complete():
    result = parse_ddl('CREATE TABLE t (id integer); ALTER TABLE t RENAME COLUMN id TO x;')
    assert result['warnings'] and not result['tables'][0]['mappingSelectable']
    with pytest.raises(ValueError): parse_ddl('CREATE TABLE t(id integer); DROP TABLE t;')
    with pytest.raises(ValueError): parse_ddl('CREATE TABLE t(id integer); CREATE TABLE t(id text);')
    result = parse_ddl('CREATE TABLE "Mixed" ("Id" integer);')
    assert result['tables'][0]['name'] == 'Mixed' and result['tables'][0]['columns'][0]['name'] == 'Id'


def test_explicit_priority_decimal_and_lazy_conditions():
    for value in [False, 0, '']:
        assert evaluate(expr('coalesce', ref('body.site'), lit(22)), {'body': {'site': value}}) == value
    assert evaluate(expr('coalesce', ref('body.site'), lit(22)), {'body': {}}) == 22
    assert evaluate(expr('round', expr('mul', lit(0.12345), lit(10)), lit(3)), {}) == Decimal('1.235')
    assert evaluate(expr('if', lit(False), expr('div', lit(1), lit(0)), lit(2)), {}) == 2
    assert not equal(True, 1)
    assert equal([1, 2, 2], [2.0, 1, 2], False)
    assert not equal([1, 2, 2], [1, 1, 2], False)


@pytest.mark.parametrize('reference', ['response.value', 'steps.later.value', '__import__.os'])
def test_rules_do_not_derive_expected_from_response_or_future(reference):
    with pytest.raises(ValueError): validate_rules({'steps': [], 'assertions': [{'path': 'value', 'expected': ref(reference)}]})


def test_aggregation_freezes_pre_api_values_and_records_mismatch(monkeypatch):
    source = [{'site': 1, 'value': Decimal('0.1')}, {'site': 1, 'value': Decimal('0.2')}, {'site': 2, 'value': Decimal('0.4')}]
    query = {'engine': 'postgres', 'table': 'readings', 'columns': ['site', 'value']}
    rules = {'steps': [{'name': 'rows', 'query': query}, {'name': 'totals', 'aggregate': {
        'source': ref('steps.rows'), 'group_by': ['site'], 'column': 'value', 'operation': 'sum', 'output': 'total'}}],
        'assertions': [{'path': 'data', 'expected': ref('steps.totals'), 'ordered': False}]}
    monkeypatch.setattr(backend, 'read', lambda *_: deepcopy(source))
    evidence = {}; prepared = backend.prepare(rules, {}, {}, evidence)
    source[0]['value'] = 999
    assert backend.verify(rules, prepared, {'data': [{'site': 2, 'total': .4}, {'site': 1, 'total': .3}]}, {}, evidence)[0]
    evidence = {}; backend.prepare(rules, {}, {}, evidence)
    assert not backend.verify(rules, prepared, {'data': [{'site': 1, 'total': 999}]}, {}, evidence)[0]
    assert evidence['assertions'][0]['expected'][0]['total'] == Decimal('.3')
    assert evidence['assertions'][0]['verdict'] == 'NG'


BULK = {'measurement': 'readings', 'action': 'update',
        'scope': {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-03T00:00:00Z', 'tags': {}},
        'target': {'start': '2026-01-02T00:00:00Z', 'end': '2026-01-02T00:00:00Z', 'tags': {'site': 'a'}},
        'fields': {'value': expr('mul', ref('point.value'), lit(10))}}


@pytest.mark.parametrize('bad', ['range', 'tag', 'nanosecond', 'timezone'])
def test_bulk_bounds_rejected(bad):
    check = deepcopy(BULK)
    if bad == 'range': check['target']['start'] = '2025-01-01T00:00:00Z'
    if bad == 'tag': check['scope']['tags']['site'] = 'b'
    if bad == 'nanosecond': check['scope']['start'] = '2026-01-01T00:00:00.0000000001Z'
    if bad == 'timezone': check['scope']['start'] = '2026-01-01T00:00:00'
    with pytest.raises(ValueError): validate_bulk(check)


@pytest.mark.parametrize('fault', [None, 'guard', 'missing', 'extra', 'wrong-value', 'noop'])
def test_bulk_checks_full_scope(monkeypatch, fault):
    rows = {(1, 'a'): {'time': '2026-01-01T00:00:00Z', 'site': 'a', 'value': 1},
            (1767312000000000000, 'a'): {'time': '2026-01-02T00:00:00Z', 'site': 'a', 'value': 2},
            (1767312000000000000, 'b'): {'time': '2026-01-02T00:00:00Z', 'site': 'b', 'value': 3}}
    monkeypatch.setattr(influx_bulk, 'snapshot', lambda *_: (rows, ['site'], ['value']))
    evidence = influx_bulk.prepare(BULK, {}, {})
    assert evidence['target_count'] == 1 and evidence['guard_count'] == 2
    after = {i: deepcopy(row) for i, row in enumerate(evidence['expected_points'])}
    if fault == 'guard': after[0]['value'] = 9
    if fault == 'missing': del after[1]
    if fault == 'extra': after[3] = {**after[0], 'site': 'c'}
    if fault == 'wrong-value': after[1]['value'] = 21
    if fault == 'noop': after = rows
    monkeypatch.setattr(influx_bulk, 'snapshot', lambda *_: (after, ['site'], ['value']))
    assert influx_bulk.verify(BULK, {}, evidence)[0] is (fault is None)


def test_bulk_no_target_never_passes(monkeypatch):
    monkeypatch.setattr(influx_bulk, 'snapshot', lambda *_: ({}, ['site'], ['value']))
    with pytest.raises(DBResponseCheckUnverified): influx_bulk.prepare(BULK, {}, {})


def test_rules_and_bulk_are_part_of_reviewed_identity():
    rules = {'steps': [], 'assertions': [{'path': 'value', 'expected': lit(1)}]}
    raw = {'name': 'rules', 'request': {'operationId': 'test'}, 'expectation_rules': rules}
    before = _parse_scenario(raw, {})
    rules['assertions'][0]['expected'] = lit(2)
    assert before.case_id != _parse_scenario(raw, {}).case_id
    assert before.case_definition()['expectationRules']['assertions'][0]['expected'] == lit(1)


def test_secret_references_remain_comparable_but_do_not_leak_to_evidence():
    import json
    rules = {'steps': [{'name': 'value', 'value': expr('string', ref('body.password'))}],
             'assertions': [{'path': 'echo', 'expected': ref('steps.value')}]}
    evidence = {}; prepared = backend.prepare(rules, {'body': {'password': 'fixture-only-secret-value'}}, {}, evidence)
    assert backend.verify(rules, prepared, {'echo': 'fixture-only-secret-value'}, {}, evidence)[0]
    assert 'fixture-only-secret-value' not in json.dumps(evidence)
    assert evidence['assertions'][0]['actual'] == '[REDACTED]'


def test_preparation_failure_never_sends_api(monkeypatch):
    from unittest.mock import Mock
    import requests
    import db_scenario_runner as runner
    rules = {'steps': [{'name': 'bad', 'value': expr('div', lit(1), lit(0))}],
             'assertions': [{'path': 'value', 'expected': ref('steps.bad')}]}
    scenario = _parse_scenario({'name': 'invalid expectation', 'request': {'operationId': 'test'}, 'expectation_rules': rules}, {})
    call = Mock(); monkeypatch.setattr(runner, '_call_api', call)
    result = runner._run_scenario(scenario, {'paths': {'/test': {'post': {'operationId': 'test'}}}},
                                  'http://localhost', {}, {}, requests.Session(), evidence={})
    assert result[0] is False and '[UNVERIFIED]' in result[1]
    call.assert_not_called()


def test_read_query_does_not_silently_truncate(monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def client(_): yield object()
    monkeypatch.setattr(backend, 'get_influxdb_config', lambda _: {})
    monkeypatch.setattr(backend.influx_response, '_client', client)
    monkeypatch.setattr(backend.influx_response, '_validate_columns', lambda *_: None)
    monkeypatch.setattr(backend.influx_response, '_select', lambda *_: [{'value': 1}] * 5001)
    with pytest.raises(DBResponseCheckUnverified): backend.read({'engine': 'influxdb', 'table': 'readings', 'columns': ['value']}, {}, {})


def test_pg_dump_style_defaults_and_generated_columns():
    ddl = '''CREATE TABLE public.sample (id bigint GENERATED ALWAYS AS IDENTITY, n numeric);
      ALTER TABLE public.sample ALTER COLUMN n SET DEFAULT 1.25;
      ALTER TABLE ONLY public.sample ADD CONSTRAINT sample_pk PRIMARY KEY (id);
      ALTER TABLE public.sample OWNER TO lab;'''
    result = parse_ddl(ddl)
    table = result['tables'][0]
    assert table['mappingSelectable']
    assert table['columns'][0]['generated'] and not table['columns'][0]['nullable']
    assert table['columns'][1]['default'] == '1.25'
    changed = parse_ddl(ddl + 'ALTER TABLE sample ALTER COLUMN n DROP DEFAULT; ALTER TABLE sample ALTER COLUMN n SET NOT NULL;')
    assert changed['tables'][0]['columns'][1]['default'] is None
    assert not changed['tables'][0]['columns'][1]['nullable']
