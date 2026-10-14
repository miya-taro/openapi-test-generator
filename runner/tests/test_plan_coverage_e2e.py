"""Exercise missing plan cases over real HTTP/PostgreSQL, with known faulty APIs."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg2
from psycopg2.extras import Json
import pytest
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'runner')]
from auth_login import perform_login, build_auth_header, load_auth_config
from contract_db_guard import execute_guarded
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from docs.authenticated_fixture import AuthenticatedFixture
from docs.login_fixture_api import LoginFixture
from docs.plan_fixture_api import PlanFixture, valid_plan_request
from docs.plan_get_fixture_api import PlanGetFixture, QUANTITIES
from docs.plan_test_suites import (post_contract, post_suite, post_mapping, post_body,
                                  get_suite, empty_get_case, write_examples)
from http_client import execute_with_openapi
from models import RunCase
from request_builder import build_request_body
from response_schema import from_run_case
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids
from src.parser import parse_openapi
from verifier import verify

DB_REQUIRED = pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires dedicated PostgreSQL')


def test_reusable_suites_match_ui_mapping_and_committed_examples(tmp_path):
    code = """import {planInsertMappings} from './gui-tauri/src/insert-editor.js';
console.log(JSON.stringify(Object.fromEntries(planInsertMappings().map(x=>[x.column,x.rule]))));"""
    result = subprocess.run(['node', '--input-type=module', '-e', code], cwd=ROOT,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == post_mapping()['columns']
    write_examples(tmp_path)
    for path in tmp_path.iterdir():
        assert json.loads(path.read_text()) == json.loads((ROOT/'examples/plan-test-suites'/path.name).read_text())
    post = post_suite()['scenarios']
    assert len(post) == 28
    assert all(valid_plan_request(c['request']['body']) for c in post[:25])
    assert all(not valid_plan_request(c['request']['body']) for c in post[25:])
    assert len(get_suite()['scenarios']) == 32
    failures = json.loads((ROOT/'examples/login/failure-scenarios.json').read_text(encoding='utf-8'))
    for suite in (post_suite(), get_suite(), failures):
        parsed = parse_scenarios(yaml.safe_dump(suite))
        assert len({case.case_id for case in parsed}) == len(parsed)


def output_dir(tmp_path, name):
    path = Path(os.environ.get('OTG_PLAN_COVERAGE_EVIDENCE_DIR', tmp_path/'evidence')) / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_scenario(fixture, config, api, raw, output, label, expected=True):
    case = parse_scenarios(yaml.safe_dump({'scenarios': [raw]}))[0]
    evidence = {}
    with requests.Session() as session:
        outcome = _run_scenario(case, api, fixture.url, {'postgres': config}, {}, session, evidence=evidence)
    (output/f'{label}.json').write_text(json.dumps(_safe_evidence(evidence), ensure_ascii=False, indent=2), encoding='utf-8')
    assert outcome[0] is expected, (label, outcome)
    return evidence


@DB_REQUIRED
def test_all_generated_plan_post_errors_and_partial_commits(tmp_path, monkeypatch):
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    fixture = PlanFixture(config)
    login = LoginFixture()
    gateway = AuthenticatedFixture(login.url, fixture.url, '/v1/plan/set')
    output = output_dir(tmp_path, 'post-errors')
    try:
        spec = tmp_path/'post.json'
        spec.write_text(json.dumps(post_contract(fixture.table, fixture.site_table)), encoding='utf-8')
        api = parse_openapi(str(spec))
        params, bodies = extract_specs(api)
        generated = assign_ids(generate_test_cases(params, bodies,
                               {'includeNormal': False, 'includeAbnormal': True}, extract_auth_specs(api)))
        assert len(generated) >= 220
        records = []
        auth = load_auth_config(str(ROOT/'examples/login/auth.json'))
        with requests.Session() as session:
            token = perform_login(gateway.url, auth, session)
            header = build_auth_header(token, auth)
            monkeypatch.setenv('TEST_AUTH_HEADER_NAME', header[0])
            monkeypatch.setenv('TEST_AUTH_HEADER_VALUE', header[1])
            # Preserve existing rows as well as checking that new rows are not added.
            fixture.insert(post_body())
            for raw in generated:
                case = RunCase(*(raw[k] for k in ('id', 'operationId', 'path', 'method', 'in', 'paramName',
                                                'inputValue', 'expectedStatus', 'expectedResponseBody',
                                                'expectedResponseHeader', 'expectedResponseTime', 'expectedResult')))
                # 400 is the declared fixture validation outcome, not any 4xx.
                case.expected_status = '400'
                prepared = build_request_body(case, api)
                if case.param_in == 'header':
                    assert valid_plan_request(prepared.json_body), raw
                else:
                    assert prepared is None or not valid_plan_request(prepared.json_body), raw
                guard = []
                result, failures = execute_guarded(case, api, {'postgres': config},
                    lambda case=case: execute_with_openapi(case, gateway.url, api, session), guard)
                verdict, detail = verify(result, from_run_case(case, api))
                assert result.actual_status == 400 and verdict == 'OK' and not failures, (raw, result.error, detail, failures)
                assert gateway.calls[-1]['authenticated']
                assert len(guard[0]['scopes']) == 2 and all(x['verdict'] == 'OK' for x in guard[0]['scopes'])
                records.append({'id': case.id, 'field': case.param_name, 'keyword': raw['keyword'],
                                'status': result.actual_status, 'verdict': verdict, 'db_unchanged': True,
                                'curl': result.curl_command})
            # These are explicit second-element errors; automatic mutation usually targets element 0.
            cases = post_suite(fixture.table, fixture.site_table)['scenarios'][-3:]
            for index, raw in enumerate(cases):
                evidence = run_scenario(fixture, config, api, raw, output, f'partial-{index}')
                assert evidence['response']['status'] == 400
            for fault in ('partial-write', 'error-write', 'accept-invalid'):
                fixture.fault = fault
                evidence = run_scenario(fixture, config, api, cases[0], output, 'fault-'+fault, False)
                if fault != 'accept-invalid':
                    assert evidence['response']['status'] == 400
                    assert any(scope['verdict'] == 'NG' for scope in evidence['db_unchanged'])
                else:
                    assert evidence['response']['status'] == 200
        (output/'generated-cases.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Plan POST: {len(records)} generated errors + 3 partial-commit cases passed; 3 faults detected')
    finally:
        gateway.close()
        login.close()
        fixture.close()


@DB_REQUIRED
def test_plan_get_boundaries_combinations_and_explicit_empty_results(tmp_path):
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    fixture = PlanGetFixture(config)
    output = output_dir(tmp_path, 'get-boundaries')
    api = parse_openapi(str(ROOT/'examples/plan-get/openapi.json'))
    try:
        cases = get_suite(fixture.definition())['scenarios']
        for index, raw in enumerate(cases):
            evidence = run_scenario(fixture, config, api, raw, output, f'case-{index+1:02}')
            body = raw['request']['body']
            response = evidence['response']['body']
            assert response['site_id'] == 101
            expected_count = 4 if index < 27 else [1, 1, 2, 2, 4][index-27]
            assert sum(len(plan['controls']) for plan in response['plans']) == expected_count
            expected_type = body.get('type', '2-1')
            assert {plan['type'] for plan in response['plans']} == {expected_type}
            if 'correct' in body:
                assert all(control['correct'] is body['correct'] for plan in response['plans'] for control in plan['controls'])
        for fault in ('exclude-start', 'include-end'):
            fixture.fault = fault
            run_scenario(fixture, config, api, cases[27], output, 'fault-'+fault, False)
        fixture.fault = 'ignore-correct'
        false_case = next(c for c in cases if c['request']['body'].get('correct') is False)
        run_scenario(fixture, config, api, false_case, output, 'fault-ignore-correct', False)
        fixture.fault = None
        # Both empty-result contracts are supported only when explicitly configured.
        body = {**cases[0]['request']['body'], 'start': '2099-01-01T00:00:00Z', 'end': '2099-01-02T00:00:00Z'}
        for status in (200, 400):
            fixture.empty_status = status
            expected_body = ({'site_id': 101, 'start_datetime': body['start'], 'end_datetime': body['end'], 'plans': []}
                             if status == 200 else {'error': 'no plans'})
            raw = empty_get_case(body, expected_status=status, expected_body=expected_body)
            api['paths']['/plan/control/get']['get']['responses']['400'] = {
                'description': 'Explicit fixture empty-result policy',
                'content': {'application/json': {'schema': {
                    'type': 'object', 'required': ['error'], 'properties': {'error': {'type': 'string'}}}}}}
            evidence = run_scenario(fixture, config, api, raw, output, f'empty-{status}')
            assert evidence['response']['status'] == status
            fixture.empty_status = 400 if status == 200 else 200
            run_scenario(fixture, config, api, raw, output, f'fault-empty-{status}', False)
        print('Plan GET: 32 combinations/boundaries + 2 explicit empty-result policies passed; 5 faults detected')
    finally:
        fixture.close()


# Winners are deliberately older except for the final tie-break case.
PRIORITY_CASES = [
    ('correct-before-fixed', {'correct': True}, {'fixed': True}, 'ignore-correct-force'),
    ('force-before-fixed', {'force': True}, {'fixed': True}, 'ignore-correct-force'),
    ('fixed-before-unfixed', {'fixed': True}, {}, 'ignore-fixed'),
    ('fixed-cpbs-before-null', {'fixed': True, 'cpbs_type': 0}, {'fixed': True, 'cpbs_type': None}, 'ignore-cpbs'),
    ('larger-fixed-cpbs', {'fixed': True, 'cpbs_type': 2}, {'fixed': True, 'cpbs_type': 1}, 'ignore-cpbs'),
    ('unfixed-null-before-cpbs', {'cpbs_type': None}, {'cpbs_type': 0}, 'ignore-cpbs'),
    ('latest-created', {'created_offset': 3}, {}, 'oldest'),
]


@DB_REQUIRED
def test_plan_get_priority_with_independent_known_winners(tmp_path):
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    fixture = PlanGetFixture(config)
    output = output_dir(tmp_path, 'get-priority')
    api = parse_openapi(str(ROOT/'examples/plan-get/openapi.json'))
    try:
        stamp = datetime.fromisoformat('2026-10-12T00:00:00+09:00')
        raw = fixture.definition()
        raw['request']['body']['type'] = '1-1'
        for name, winner, loser, fault in PRIORITY_CASES:
            with psycopg2.connect(**config) as conn, conn.cursor() as cur:
                cur.execute(f'DELETE FROM {fixture.table}')
                for index, (overrides, value) in enumerate(((winner, 42), (loser, 99))):
                    settings = {'correct': False, 'force': False, 'fixed': False, 'cpbs_type': 0, 'created_offset': index, **overrides}
                    row = [stamp, stamp+timedelta(seconds=settings['created_offset']), 101, '1-1',
                           settings['correct'], settings['force'], settings['fixed'], settings['cpbs_type'], 10,
                           *[value+i for i in range(len(QUANTITIES))], Json({'start_time': '00:00', 'start': {'buy': value}})]
                    cur.execute(f'INSERT INTO {fixture.table} VALUES ({",".join(["%s"]*len(row))})', row)
            fixture.fault = None
            evidence = run_scenario(fixture, config, api, raw, output, name)
            controls = evidence['response']['body']['plans'][0]['controls']
            assert len(controls) == 1 and controls[0]['buy'] == 42
            fixture.fault = fault
            run_scenario(fixture, config, api, raw, output, 'fault-'+name, False)
        print(f'Plan GET: {len(PRIORITY_CASES)} known priority winners passed; {len(PRIORITY_CASES)} faults detected')
    finally:
        fixture.close()
