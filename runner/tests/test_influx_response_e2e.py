"""Opt-in real InfluxDB 1.8 + HTTP + UI-generated mappings and runner CLIs.

OTG_INFLUX_INTEGRATION_CONFIG supplies host/port (optional credentials).
Only a uniquely named temporary database is created/dropped.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from influxdb import InfluxDBClient
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_influx_ui_generated_response_and_error_guards(tmp_path):
    config_text = os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')
    if not config_text:
        pytest.skip('OTG_INFLUX_INTEGRATION_CONFIG is not set')
    config = json.loads(config_text)
    config['database'] = 'otg_test_' + uuid.uuid4().hex[:12]
    client = InfluxDBClient(**config)
    client.create_database(config['database'])
    output = Path(os.environ.get('OTG_INFLUX_EVIDENCE_DIR', tmp_path / 'evidence'))
    output.mkdir(parents=True, exist_ok=True)
    config_path = tmp_path / 'db.json'
    config_path.write_text(json.dumps({'influxdb': config}))
    mode = 'correct'
    calls = []
    records = [dict(measurement='measure', tags={'location': loc, 'item': item},
                    time=f'2026-01-01T00:00:0{i}Z', fields={'site': site, 'value': float(i)})
               for site, loc in [(1, 'A'), (2, 'B'), (3, 'C')]
               for item in ['a', 'b', 'c'] for i in range(5)]
    def reset():
        client.query('DROP MEASUREMENT "measure"')
        client.write_points(records)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def call(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
            calls.append((self.command, body))
            if self.path.split('?')[0] == '/reject':
                points = list(client.query('SELECT * FROM measure ORDER BY time ASC').get_points())
                if mode == 'update':
                    p = points[0]
                    client.write_points([dict(measurement='measure', tags={'location': p['location'], 'item': p['item']},
                                              time=p['time'], fields={'value': p['value'] + 10})])
                elif mode == 'delete':
                    p = points[0]
                    client.query(f'DELETE FROM measure WHERE time = \'{p["time"]}\' AND location = \'{p["location"]}\' AND item = \'{p["item"]}\'')
                elif mode == 'insert':
                    client.write_points([dict(measurement='measure', tags={'location': f'new{len(points)}', 'item': 'a'},
                                              time='2026-01-01T00:00:02Z', fields={'site': 1, 'value': 1.0})])
                status, response = 400, {'error': 'invalid input'}
            else:
                # Deliberately independent API implementation: read DB and filter in Python.
                selected = []
                for p in client.query('SELECT * FROM measure').get_points():
                    loc = []
                    if 'site_id' in body: loc.append(p['site'] == body['site_id'])
                    if 'location_id' in body: loc.append(p['location'] == body['location_id'])
                    if mode != 'ignore_scope' and loc and not (all(loc) if mode == 'and_scope' else any(loc)): continue
                    if 'start' in body and mode != 'ignore_start' and p['time'] < body['start']: continue
                    if 'end' in body and mode != 'ignore_end' and p['time'] > body['end']: continue
                    if mode == 'exclude_start' and p['time'] == body.get('start'): continue
                    if mode == 'exclude_end' and p['time'] == body.get('end'): continue
                    if mode != 'ignore_items' and p['item'] not in body['items']: continue
                    if mode == 'first_item' and p['item'] != body['items'][0]: continue
                    selected.append({k: p[k] for k in ('time', 'item', 'value')})
                selected.reverse()
                if mode == 'missing': selected.pop()
                if mode == 'duplicate': selected.append(dict(selected[0]))
                if mode == 'wrong_value': selected[0]['value'] += 10
                if mode == 'wrong_nanosecond': selected[0]['time'] = selected[0]['time'].replace('Z', '.000000001Z')
                if mode == 'timezone':
                    for p in selected: p['time'] = p['time'].replace('T00:', 'T09:').replace('Z', '+09:00')
                status, response = 200, {'result': selected}
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = call
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f'http://127.0.0.1:{server.server_port}'
    request_schema = {'type': 'object', 'required': ['items'], 'properties': {
        'site_id': {'type': 'integer'}, 'location_id': {'type': 'string'},
        'start': {'type': 'string', 'format': 'date-time'}, 'end': {'type': 'string', 'format': 'date-time'},
        'items': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1}},
        'x-otg-presence-rules': [{'kind': 'atLeastOne', 'fields': ['site_id', 'location_id']},
                               {'kind': 'together', 'fields': ['start', 'end']}]}
    response_schema = {'type': 'object', 'required': ['result'], 'properties': {'result': {
        'type': 'array', 'items': {'type': 'object', 'required': ['time', 'item', 'value'], 'properties': {
            'time': {'type': 'string', 'format': 'date-time'}, 'item': {'type': 'string'}, 'value': {'type': 'number'}}}}}}
    operation = {'operationId': 'measure', 'requestBody': {'content': {'application/json': {'schema': request_schema}}},
                 'responses': {'200': {'description': 'OK', 'content': {'application/json': {'schema': response_schema}}}}}
    spec = tmp_path / 'api.json'
    spec.write_text(json.dumps({'openapi': '3.1.0', 'paths': {'/measure': {'get': operation}}}))
    body = {'site_id': 1, 'location_id': 'B', 'start': '2026-01-01T00:00:01Z', 'end': '2026-01-01T00:00:03Z', 'items': ['a', 'b']}
    form = {'operation': {'operationId': 'measure', 'method': 'GET', 'path': '/measure',
                         'requestSchema': request_schema, 'responseSchema': response_schema, 'parameters': []},
            'name': 'Influx期間内照合', 'engine': 'influxdb', 'table': 'measure', 'requestBody': body,
            'responseStatus': '200', 'responseShape': 'array', 'responseArrayPath': 'result',
            'readMappings': [{'source': c, 'target': c} for c in ['time', 'item', 'value']],
            'readFilters': [{'source': 'body', 'parameter': p, 'column': c, 'operator': op, **({'group': 'scope'} if p in ['site_id', 'location_id'] else {})}
                            for p, c, op in [('site_id', 'site', '='), ('location_id', 'location', '='), ('start', 'time', '>='), ('end', 'time', '<='), ('items', 'item', 'in')]]}
    def generate(form):
        command = "import {buildDbScenarios} from './gui-tauri/src/db-scenario-editor.js'; console.log(JSON.stringify(buildDbScenarios(JSON.parse(process.argv[1]))));"
        result = subprocess.run(['node', '--input-type=module', '-e', command, json.dumps(form)], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    def run(scenarios, label, code=0):
        path = tmp_path / 'scenarios.yaml'
        path.write_text(yaml.safe_dump({'scenarios': {'list': scenarios}}, allow_unicode=True))
        result = subprocess.run([sys.executable, str(ROOT / 'runner/db_scenario_runner.py'), str(path), str(spec),
                                 '--base-url', base_url, '--config', str(config_path), '--skip-health-check', '--report-output', str(output / f'{label}.xlsx'),
                                 '--evidence-output', str(output / f'{label}.json')], capture_output=True, text=True)
        assert result.returncode == code, result.stdout + result.stderr
    try:
        reset()
        scenarios = generate(form)
        assert scenarios[0]['db_response_check']['engine'] == 'influxdb'
        for mode in ['correct', 'timezone', 'ignore_scope', 'and_scope', 'ignore_start', 'ignore_end',
                     'exclude_start', 'exclude_end', 'ignore_items', 'first_item', 'missing', 'duplicate', 'wrong_value', 'wrong_nanosecond']:
            run(scenarios, mode, 0 if mode in ['correct', 'timezone'] else 1)
        mode = 'correct'
        expanded = generate({**form, 'expandCombinations': True})
        assert len(expanded) > 1
        run(expanded, 'combinations')
        # Missing witness data must stop before HTTP and cannot produce a pass.
        client.query("DELETE FROM measure WHERE item = 'c'")
        before = len(calls)
        run(scenarios, 'unverified', 2)
        assert len(calls) == before
        reset()
        scope = {'engine': 'influxdb', 'table': 'measure', 'columns': ['time', 'location', 'item', 'site', 'value'],
                 'time_start': '2026-01-01T00:00:00Z', 'time_end': '2026-01-01T00:00:04Z', 'where': {}}
        # UI no-change setting works on every HTTP method.
        for method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']:
            unchanged = generate({**form, 'mode': 'unchanged', 'operation': {**form['operation'], 'method': method},
                                  'unchangedStatus': '200', 'unchangedColumns': ','.join(scope['columns']),
                                  'timeStart': scope['time_start'], 'timeEnd': scope['time_end']})
            method_api = copy.deepcopy(operation)
            spec.write_text(json.dumps({'openapi': '3.1.0', 'paths': {'/measure': {method.lower(): method_api}}}))
            run(unchanged, f'unchanged-{method}')
        # Automatically generated 4xx cases use InfluxDB-only config, for all five methods.
        paths = {'/reject': {method: {'operationId': method, 'parameters': [{'name': 'id', 'in': 'query', 'required': True, 'schema': {'type': 'integer', 'minimum': 1}}],
                   'responses': {'200': {'description': 'OK'}, '400': {'description': 'Invalid'}},
                   'x-otg-error-db-unchanged': [scope]} for method in ['get', 'post', 'put', 'patch', 'delete']}}
        spec.write_text(json.dumps({'openapi': '3.1.0', 'paths': paths}))
        cases, excel = tmp_path / 'cases.json', tmp_path / 'cases.xlsx'
        result = subprocess.run([sys.executable, str(ROOT / 'src/cli.py'), str(spec), '--no-normal', '-o', str(cases), '--excel-output', str(excel)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        count = len(json.loads(cases.read_text())['cases'])
        assert count == 20
        for mode in ['correct', 'update', 'insert', 'delete']:
            reset()
            result = subprocess.run([sys.executable, str(ROOT / 'runner/runner.py'), str(excel), str(spec), '--base-url', base_url,
                                     '--config', str(config_path), '--skip-health-check', '--output', str(output / f'guard-{mode}.xlsx')], capture_output=True, text=True)
            assert result.returncode == (0 if mode == 'correct' else 1), result.stdout + result.stderr
            evidence = json.loads((output / f'guard-{mode}-db-evidence.json').read_text())
            assert len(evidence) == count
            assert all(item['scopes'][0]['verdict'] == ('OK' if mode == 'correct' else 'NG') for item in evidence)
        (output / 'summary.json').write_text(json.dumps({'response_faults_detected': 12, 'normal_combinations': len(expanded),
                                                       'guard_normal': count, 'guard_faults_detected': count * 3, 'http_calls': len(calls)}, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.drop_database(config['database'])
        client.close()
