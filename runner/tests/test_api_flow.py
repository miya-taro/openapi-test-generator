"""Real HTTP checks through the same reviewed-plan pytest runner used by the UI."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import openpyxl
import pytest
import requests
from werkzeug.wrappers import Response

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runner'))
sys.path.insert(0, str(ROOT))
from api_flow import resolve, validate_operations
from db_scenario import parse_scenarios, ScenarioError
from db_scenario_runner import _run_scenario
from execution_plan import db_case
from workflow.case_master import build_case_master, write_case_master


def operation(name):
    return {'operationId': name, 'responses': {'200': {'description': 'ok', 'content': {
        'application/json': {'schema': {'type': 'object'}}}}}}


API = {'openapi': '3.0.3', 'info': {'title': 'jobs', 'version': '1'}, 'paths': {
    '/jobs': {'post': operation('create')},
    '/jobs/{id}': {'get': operation('get'), 'delete': operation('delete')},
}}
FLOW = {'name': '作成して完了待ち、値を確認、削除',
        'request': {'operationId': 'get', 'path_params': {'id': '{{steps.create.id}}'}},
        'response_check': {'expect': {'status': 200, 'body': {'value': 42}}},
        'api_flow': {'before': [{'name': 'create', 'request': {'operationId': 'create', 'body': {'value': 42}}, 'expect_status': 200}],
                     'cleanup': [{'name': 'delete', 'request': {'operationId': 'delete', 'path_params': {'id': '{{steps.create.id}}'}}, 'expect_status': 200}]},
        'poll': {'path': 'state', 'equals': 'done', 'timeout': 0.4, 'interval': 0.05}}


def fixture_api(server, *, fault=None):
    calls = []
    def create(request):
        calls.append('create')
        assert request.json == {'value': 42}
        return Response(json.dumps({'id': 7}), status=500 if fault == 'create' else 200, content_type='application/json')
    def get(request):
        calls.append('get')
        return Response(json.dumps({'state': 'running' if fault == 'timeout' or calls.count('get') == 1 else 'done',
                                    'value': 99 if fault == 'value' else 42}), content_type='application/json')
    def delete(request):
        calls.append('delete')
        return Response('{}', status=500 if fault == 'cleanup' else 200, content_type='application/json')
    server.expect_request('/jobs', method='POST').respond_with_handler(create)
    server.expect_request('/jobs/7', method='GET').respond_with_handler(get)
    server.expect_request('/jobs/7', method='DELETE').respond_with_handler(delete)
    return calls


@pytest.mark.parametrize('fault', [None, 'create', 'value', 'timeout', 'cleanup'])
def test_real_http_chain_detects_faults_and_always_cleans_up(httpserver, fault):
    calls = fixture_api(httpserver, fault=fault)
    scenario = parse_scenarios(json.dumps({'scenarios': [FLOW]}))[0]
    evidence = {}
    with requests.Session() as session:
        ok, detail, status, _, cleanup = _run_scenario(scenario, API, httpserver.url_for('/'), {}, {}, session, evidence=evidence)
    assert ok is (fault is None), (detail, status)
    assert calls.count('create') == 1
    assert calls[-1] == 'delete'
    if fault == 'create':
        assert calls.count('get') == 0
        assert evidence['api_steps'][0]['verdict'] == 'NG'
    elif fault == 'timeout':
        assert '期限' in detail
    elif fault == 'cleanup':
        assert cleanup
    else:
        assert calls.count('get') == 2
    assert bool(cleanup) is (fault == 'cleanup')


def test_pytest_plan_rerun_excel_and_json_with_no_db_config(tmp_path, httpserver):
    calls = fixture_api(httpserver)
    api = tmp_path / 'openapi.json'; api.write_text(json.dumps(API), encoding='utf-8')
    scenarios = tmp_path / 'flows.json'; scenarios.write_text(json.dumps({'scenarios': [FLOW]}), encoding='utf-8')
    master = build_case_master('flows', None, scenarios, api)
    assert db_case(master['cases'][0]).case_definition() == parse_scenarios(scenarios.read_text(encoding='utf-8'))[0].case_definition()
    path = tmp_path / 'master.json'; write_case_master(master, path)
    command = [sys.executable, str(ROOT / 'runner/pytest_runner.py'), str(path), '--kind', 'db-scenario',
               '--base-url', httpserver.url_for('/'), '--skip-health-check', '--output', str(tmp_path / 'result.xlsx'),
               '--junit-xml', str(tmp_path / 'junit.xml'), '--case-ids', master['cases'][0]['caseId']]
    proc = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads((tmp_path / 'result.json').read_text(encoding='utf-8'))
    assert payload['cases'][0]['status'] == 'passed'
    assert len(payload['cases'][0]['evidence']['poll_attempts']) == 2
    book = openpyxl.load_workbook(tmp_path / 'result.xlsx')
    assert book['API手順と完了待ち'].max_row == 4
    assert calls == ['create', 'get', 'get', 'delete']


def test_preflight_rejects_polling_mutations_and_forward_references():
    raw = copy.deepcopy(FLOW)
    raw['api_flow']['before'][0]['poll'] = raw['poll']
    with pytest.raises(ValueError, match='GET'):
        validate_operations(parse_scenarios(json.dumps({'scenarios': [raw]}))[0], API)
    raw = copy.deepcopy(FLOW)
    raw['api_flow']['before'][0]['request']['body']['value'] = '{{steps.future.id}}'
    with pytest.raises(ValueError, match='前に'):
        validate_operations(parse_scenarios(json.dumps({'scenarios': [raw]}))[0], API)


@pytest.mark.parametrize('value', [0, False, None, '007', [1, 2], {'a': 2}])
def test_capture_preserves_types_and_supports_array_paths(value):
    resolved = resolve({'value': '{{steps.create.items.0}}'}, {'create': {'items': [value]}})
    assert type(resolved['value']) is type(value)
    assert resolved['value'] == value


@pytest.mark.parametrize('poll', [{'path': 'state', 'equals': 'done', 'timeout': -1, 'interval': 1},
                                {'path': '', 'equals': 'done', 'timeout': 2, 'interval': 1}])
def test_invalid_wait_rejected_before_execution(poll):
    raw = {**FLOW, 'poll': poll}
    with pytest.raises(ScenarioError):
        parse_scenarios(json.dumps({'scenarios': [raw]}))


def test_cleanup_cannot_use_stale_result_when_main_was_not_sent(httpserver):
    from api_flow import run_flow
    raw = copy.deepcopy(FLOW)
    raw['api_flow']['before'] = []
    raw['request']['path_params'] = {'id': 7}
    raw['api_flow']['cleanup'][0]['request']['path_params']['id'] = '{{steps.result.id}}'
    scenario = parse_scenarios(json.dumps({'scenarios': [raw]}))[0]
    with requests.Session() as session:
        outcome = run_flow(lambda *args: (False, '準備失敗', 'ERR', {'id': 999}, []), scenario,
                           API, httpserver.url_for('/'), {}, {'id': 999}, session, False, None, {})
    assert outcome[0] is False
    assert outcome[4]
    assert not httpserver.log


def test_api_flow_checks_postgres_before_cleanup(tmp_path, httpserver):
    import os
    import uuid
    config_text = os.environ.get('OTG_INTEGRATION_DB_CONFIG')
    if not config_text:
        pytest.skip('requires dedicated PostgreSQL')
    import psycopg2
    config = json.loads(config_text)
    table = 'flow_' + uuid.uuid4().hex[:12]
    with psycopg2.connect(**config) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'CREATE TABLE {table} (id integer PRIMARY KEY, value integer)')
    fault = [False]
    def create(request):
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'INSERT INTO {table} VALUES (%s, %s)', (7, 43 if fault[0] else 42))
        return Response('{"id":7}', content_type='application/json')
    def delete(request):
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'DELETE FROM {table} WHERE id=7')
        return Response('{}', content_type='application/json')
    httpserver.expect_request('/jobs', method='POST').respond_with_handler(create)
    httpserver.expect_request('/jobs/7', method='GET').respond_with_json({'state': 'done', 'value': 42})
    httpserver.expect_request('/jobs/7', method='DELETE').respond_with_handler(delete)
    raw = copy.deepcopy(FLOW)
    raw['db_check'] = {'engine': 'postgres', 'table': table, 'where': {'id': '{{steps.create.id}}'}, 'expect': {'exists': True, 'columns': {'value': 42}}}
    scenario = parse_scenarios(json.dumps({'scenarios': [raw]}))[0]
    try:
        for damaged in (False, True):
            fault[0] = damaged
            with requests.Session() as session:
                result = _run_scenario(scenario, API, httpserver.url_for('/'), {'postgres': config}, {}, session, evidence={})
            assert result[0] is not damaged, result
            with psycopg2.connect(**config) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f'SELECT count(*) FROM {table}')
                    assert cursor.fetchone()[0] == 0
    finally:
        with psycopg2.connect(**config) as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'DROP TABLE {table}')


def test_unknown_db_expectation_cannot_silently_pass():
    raw = copy.deepcopy(FLOW)
    raw['db_check'] = {'engine': 'postgres', 'table': 'jobs', 'expect': {'value': 42}}
    with pytest.raises(ScenarioError, match='未対応'):
        parse_scenarios(json.dumps({'scenarios': [raw]}))
