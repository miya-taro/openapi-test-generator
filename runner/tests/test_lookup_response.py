"""Lookup expectations must stay independent of the request sent to the API."""
import copy
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))
from db_scenario import DBResponseCheck, DBResponseFilter, parse_scenarios, ScenarioError
from db_backends import lookup_response as lookup, postgres_backend as pg

CONFIG = {'postgres': {'host': 'localhost', 'port': 5432, 'dbname': 'db', 'user': 'u', 'password': 'p'}}
RULE = {'engine': 'postgres', 'table': 't_site', 'match_column': 'location_id', 'value_column': 'site_id',
        'cardinality': 'one', 'on_empty': 'unverified', 'value_type': 'string'}


def check(rule=None, source='body'):
    rule = dict(RULE if rule is None else rule)
    return DBResponseCheck('measure', {'value': 'value'}, [DBResponseFilter(
        source, 'location_id', 'site_id', '=' if rule['cardinality'] == 'one' else 'in', False, lookup=rule)])


@pytest.mark.parametrize('source', ['body', 'query', 'path'])
def test_lookup_values_are_used_only_for_db_expectations(monkeypatch, source):
    definition = check(source=source)
    params = {'body': {}, 'query': {}, 'path': {}}
    params[source]['location_id'] = 'A'
    before = copy.deepcopy(params)
    monkeypatch.setattr(lookup, '_read_values', lambda *args: [11])
    def prepare(resolved, config, query, path, body):
        assert {'body': body, 'query': query, 'path': path}[source]['location_id'] == '11'
        assert resolved.filters[0].lookup is None and not resolved.filters[0].auto
        return pg.PreparedDBResponse(query, path, [{'value': 3}])
    monkeypatch.setattr(pg, 'prepare_db_response_check', prepare)
    evidence = []
    prepared, status = lookup.prepare(definition, CONFIG, params['query'], params['path'], params['body'], evidence)
    assert params == before and definition.filters[0].lookup == RULE
    assert prepared.query_params == params['query'] and prepared.path_params == params['path']
    assert status is None and evidence[0]['values'] == ['11']


def test_multiple_ids_are_all_used_and_deduplicated(monkeypatch):
    definition = check({**RULE, 'cardinality': 'many'})
    monkeypatch.setattr(lookup, '_read_values', lambda *args: [11, 22, 11])
    def prepare(resolved, config, query, path, body):
        assert resolved.filters[0].operator == 'in' and body['location_id'] == ['11', '22']
        return pg.PreparedDBResponse(query, path, [])
    monkeypatch.setattr(pg, 'prepare_db_response_check', prepare)
    records = []
    lookup.prepare(definition, CONFIG, {}, {}, {'location_id': 'MULTI'}, records)
    assert records[0]['matched_rows'] == 3


@pytest.mark.parametrize('values,rule', [([], RULE), ([11, 22], RULE), ([11, 11], RULE), ([None], RULE),
    ([1.5], {**RULE, 'value_type': 'integer'}), (list(range(1001)), {**RULE, 'cardinality': 'many'})])
def test_ambiguous_missing_or_unbounded_lookup_stops_before_api(monkeypatch, values, rule):
    monkeypatch.setattr(lookup, '_read_values', lambda *args: values)
    with pytest.raises(pg.DBResponseCheckUnverified):
        lookup.prepare(check(rule), CONFIG, {}, {}, {'location_id': 'A'}, [])


@pytest.mark.parametrize('policy,status', [('empty', None), ('status', 404)])
def test_zero_result_uses_explicit_policy_without_querying_all_measurements(monkeypatch, policy, status):
    rule = {**RULE, 'on_empty': policy, **({'empty_status': status} if status else {})}
    monkeypatch.setattr(lookup, '_read_values', lambda *args: [])
    monkeypatch.setattr(pg, 'prepare_db_response_check', lambda *args: pytest.fail('No unfiltered query permitted'))
    prepared, actual = lookup.prepare(check(rule), CONFIG, {}, {}, {'location_id': 'MISSING'}, [])
    assert prepared.expected_rows == [] and actual == status


def test_zero_or_branch_cannot_hide_other_active_condition(monkeypatch):
    definition = check({**RULE, 'on_empty': 'empty'})
    definition.filters[0].group = 'A'
    definition.filters.append(DBResponseFilter('body', 'site_id', 'site_id', '=', False, group='A'))
    monkeypatch.setattr(lookup, '_read_values', lambda *args: [])
    with pytest.raises(pg.DBResponseCheckUnverified, match='OR'):
        lookup.prepare(definition, CONFIG, {}, {}, {'location_id': 'MISSING', 'site_id': 11}, [])


def test_absent_optional_lookup_never_queries_source_db(monkeypatch):
    monkeypatch.setattr(lookup, '_read_values', lambda *args: pytest.fail('omitted input'))
    monkeypatch.setattr(pg, 'prepare_db_response_check', lambda c, config, q, p, b: pg.PreparedDBResponse(q, p, []))
    lookup.prepare(check(), CONFIG, {}, {}, {}, [])


def test_parser_keeps_lookup_in_definition_and_case_identity():
    raw = {'name': 'lookup', 'request': {'operationId': 'get', 'body': {'location_id': 'A'}},
           'db_response_check': {'table': 'measure', 'fields': {'value': 'value'}, 'filters': [
               {'source': 'body', 'parameter': 'location_id', 'column': 'site_id', 'operator': '=', 'auto': False, 'lookup': RULE}]}}
    scenario = parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))[0]
    definition = scenario.case_definition()
    assert definition['dbResponseCheck']['filters'][0]['lookup'] == RULE
    before = scenario.case_id
    scenario.db_response_check.filters[0].lookup = {**RULE, 'value_column': 'other'}
    assert scenario.case_id != before


def test_lookup_evidence_masks_credentials_by_source_and_destination_names():
    from db_scenario_runner import _safe_evidence
    record = {'parameter': 'body.location_id', 'definition': RULE, 'input_value': 'A',
              'target_column': 'site_id', 'values': ['11'], 'comparison_value': '11'}
    assert _safe_evidence(record) == record
    for key in ('match_column', 'value_column'):
        sensitive = {**record, 'definition': {**RULE, key: 'access_token'}}
        saved = _safe_evidence(sensitive)
        if key == 'match_column':
            assert saved['input_value'] == '[REDACTED]'
        else:
            assert saved['values'] == saved['comparison_value'] == '[REDACTED]'
    saved = _safe_evidence({**record, 'parameter': 'body.password', 'target_column': 'secret'})
    assert saved['input_value'] == saved['values'] == saved['comparison_value'] == '[REDACTED]'
    assert record['input_value'] == 'A'


@pytest.mark.parametrize('change', [{'table': 't_site;DROP TABLE x'}, {'cardinality': 'first'},
                                    {'on_empty': 'guess'}, {'on_empty': 'status', 'empty_status': 200},
                                    {'raw_sql': 'SELECT 1'}, {'value_type': 'guess'}])
def test_invalid_lookup_definitions_are_rejected(change):
    raw = {'name': 'lookup', 'request': {'operationId': 'get'}, 'db_response_check': {
        'table': 'measure', 'fields': {'value': 'value'}, 'filters': [
            {'source': 'body', 'parameter': 'location_id', 'column': 'site_id', 'operator': '=', 'auto': False,
             'lookup': {**RULE, **change}}]}}
    with pytest.raises(ScenarioError):
        parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))
