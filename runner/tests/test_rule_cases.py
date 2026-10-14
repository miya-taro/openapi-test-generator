"""Rule cases must distinguish wrong results and leave existing data untouched."""
import copy
import json
import os
from pathlib import Path
import sys

import pytest
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'runner')]
from db_scenario import parse_scenarios, ResponseCheck
from response_check import check
from db_scenario_runner import _run_scenario, _safe_evidence
from docs.rule_fixture_api import RuleFixture, contract, rule_input, generate
from src.rule_test import validate_fixture, validate_collections
import rule_fixture as test_fixture



def test_collections_compare_nested_arrays_without_losing_duplicates_or_types():
    rule = ResponseCheck(collections=[{'path': 'plans[].controls[]', 'fields': ['value'], 'rows': [{'value': 1}, {'value': 2}]}])
    assert check(rule, 200, {'plans': [{'controls': [{'value': 2}, {'value': 1}]}]})[0]
    for body in [{'plans': []}, {'plans': [{'controls': [{'value': 1}, {'value': 1}]}]},
                 {'plans': [{'controls': [{'value': True}, {'value': 2}]}]}, {'plans': [{'controls': [{'value': 1}, {'value': 2}, {'value': 3}]}]}, {}]:
        assert not check(rule, 200, body)[0]
    with pytest.raises(ValueError):
        validate_collections([{'path': 'data', 'fields': [{}], 'rows': []}])
    with pytest.raises(ValueError):
        validate_fixture({'engine': 'postgres', 'table': 't', 'scope': {'site': 1}, 'rows': [{'site': True}]})


@pytest.mark.parametrize('engine,env', [('postgres', 'OTG_INTEGRATION_DB_CONFIG'), ('influxdb', 'OTG_INFLUX_INTEGRATION_CONFIG')])
def test_ui_generated_rules_real_http_db_and_faults(tmp_path, engine, env):
    if not os.environ.get(env):
        pytest.skip('requires dedicated '+engine)
    fixture = RuleFixture(engine, json.loads(os.environ[env]))
    config = {engine: fixture.config}
    evidence_dir = Path(os.environ.get('OTG_RULE_EVIDENCE_DIR', tmp_path/'evidence'))/engine
    evidence_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    def run(raw, api, expected=True, label='case'):
        scenario = parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))[0]
        evidence = {}
        with requests.Session() as session:
            result = _run_scenario(scenario, api, fixture.url, config, {}, session, evidence=evidence)
        (evidence_dir/f'{len(outcomes):03}-{label}.json').write_text(json.dumps(_safe_evidence(evidence), ensure_ascii=False, indent=2))
        assert result[0] is expected, result
        if raw.get('test_fixture'):
            assert evidence['test_fixture']['cleanup_status'] == 'OK', evidence
        outcomes.append({'label': label, 'verdict': result[0], 'status': result[2]})
        return result
    try:
        for kind in ['boundary', 'priority', 'empty', 'combinations']:
            data = rule_input(fixture, kind)
            cases = generate(data)
            # Repeat confirms cleanup allows rerunning exactly the same settings.
            for _repeat in range(2):
                for raw in cases:
                    run(raw, contract(kind), label=kind)
                    assert fixture.rows('test') == []
            faults = {'boundary': [('exclude-start', 1), ('include-end', 4), ('drop-rows', 0), ('duplicate', 2), ('wrong-value', 0)],
                      'priority': [('wrong-priority', 0)], 'empty': [], 'combinations': [('accept-invalid', 1)]}[kind]
            if kind == 'combinations':
                faults = [('accept-invalid', next(i for i, x in enumerate(cases) if x['response_check']['expect']['status'] == 400))]
            for fault, index in faults:
                fixture.fault = fault
                run(cases[index], contract(kind), expected=False, label=fault)
                assert fixture.rows('test') == []
            fixture.fault = None
        raw = generate(rule_input(fixture, 'empty', 400))[0]
        run(raw, contract('empty', 400), label='empty400')
        fixture.fault = 'wrong-empty-status'
        run(raw, contract('empty', 400), expected=False, label='wrong-empty-status')
        fixture.fault = None
        # Existing records in the requested scope prevent HTTP; never delete them.
        raw = generate(rule_input(fixture))[0]
        owned = {}; test_fixture.prepare(raw['test_fixture'], config, owned)
        before = len(fixture.calls)
        case = parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))[0]
        with requests.Session() as session:
            result = _run_scenario(case, contract(), fixture.url, config, {}, session)
        assert not result[0] and '[UNVERIFIED]' in result[1] and len(fixture.calls) == before
        assert len(fixture.rows('test')) == 2
        test_fixture.cleanup(raw['test_fixture'], config, owned)
        # Other sites are preserved through setup/run/cleanup.
        outside = copy.deepcopy(raw['test_fixture']); outside['scope']['site'] = 'other'
        for row in outside['rows']: row['site'] = 'other'
        owned = {}; test_fixture.prepare(outside, config, owned)
        run(raw, contract(), label='unrelated-site-preserved')
        assert len(fixture.rows('other')) == 2
        test_fixture.cleanup(outside, config, owned)
        (evidence_dir/'summary.json').write_text(json.dumps(outcomes, indent=2))
    finally:
        fixture.close()


@pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires dedicated PostgreSQL')
def test_fixture_setup_failure_and_cleanup_residue_are_visible():
    from contextlib import closing
    import psycopg2
    from psycopg2 import sql
    fixture = RuleFixture('postgres', json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']))
    config = {'postgres': fixture.config}
    try:
        raw = generate(rule_input(fixture))[0]
        invalid = copy.deepcopy(raw)
        invalid['test_fixture']['rows'][0]['nonexistent_column'] = 1
        case = parse_scenarios(yaml.safe_dump({'scenarios': [invalid]}))[0]
        with requests.Session() as session:
            result = _run_scenario(case, contract(), fixture.url, config, {}, session)
        assert '[UNVERIFIED]' in result[1] and not fixture.calls and not fixture.rows('test')
        # Duplicate primary keys fail atomically, leaving no partially inserted data.
        invalid = copy.deepcopy(raw)
        invalid['test_fixture']['rows'][1] = copy.deepcopy(invalid['test_fixture']['rows'][0])
        case = parse_scenarios(yaml.safe_dump({'scenarios': [invalid]}))[0]
        with requests.Session() as session:
            result = _run_scenario(case, contract(), fixture.url, config, {}, session)
        assert '[UNVERIFIED]' in result[1] and not fixture.calls and not fixture.rows('test')
        state = {}; test_fixture.prepare(raw['test_fixture'], config, state)
        with closing(psycopg2.connect(**fixture.config)) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL('INSERT INTO {} (site,datetime,value) VALUES (%s,%s,%s)').format(sql.Identifier(fixture.table)),
                        ('test', '2026-02-01T00:00:00Z', 999)); conn.commit()
        with pytest.raises(test_fixture.FixtureUnavailable):
            test_fixture.cleanup(raw['test_fixture'], config, state)
        assert state['cleanup_status'] == 'NG'
        assert len(fixture.rows('test')) == 1 and fixture.rows('test')[0]['value'] == 999
    finally:
        fixture.close()


def test_empty_json_and_boolean_parameters_are_preserved_on_the_wire(httpserver):
    from db_scenario_runner import _call_api
    httpserver.expect_request('/check/false', method='GET', query_string='correct=false&flags=true&flags=false', json={}).respond_with_json({'ok': True})
    result = _call_api(httpserver.url_for('').rstrip('/'), '/check/{flag}', 'GET', {'flag': False}, {},
                       query_params={'correct': False, 'flags': [True, False]}, send_empty_body=True)
    assert result.status == 200
    httpserver.check_assertions()


def test_path_values_cannot_change_the_url_query_or_fragment(monkeypatch):
    from types import SimpleNamespace
    import db_scenario_runner as runner
    sent = []
    def request(method, url, **kwargs):
        sent.append(url)
        return SimpleNamespace(status_code=200, text='{}', json=lambda: {}, headers={})
    monkeypatch.setattr(runner.requests, 'request', request)
    runner._call_api('http://localhost', '/item/{id}', 'GET', {'id': 'a/b?x=1#frag'}, {})
    assert sent == ['http://localhost/item/a%2Fb%3Fx%3D1%23frag']
