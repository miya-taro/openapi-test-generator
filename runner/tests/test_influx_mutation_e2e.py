"""Real HTTP/InfluxDB mutation verification using UI-generated single-point definitions."""
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

ROOT = Path(__file__).parents[2]


def test_ui_mutation_cases_against_real_api_and_influx(tmp_path):
    config_text = os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')
    if not config_text:
        pytest.skip('OTG_INFLUX_INTEGRATION_CONFIG is not set')
    config = {**json.loads(config_text), 'database': 'otg_mutation_' + uuid.uuid4().hex[:12]}
    client = InfluxDBClient(**config)
    client.create_database(config['database'])
    config_path = tmp_path / 'config.json'
    config_path.write_text(json.dumps({'influxdb': config}))
    output = Path(os.environ.get('OTG_INFLUX_EVIDENCE_DIR', tmp_path / 'evidence')) / 'mutations'
    output.mkdir(parents=True, exist_ok=True)
    when = '2026-01-01T00:00:00Z'
    fault, calls = 'correct', []

    def point(value, when=when, **extra):
        return {'measurement': 'measure', 'time': when, 'tags': {'item': 'a'}, 'fields': {'value': value, **extra}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def call(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
            calls.append(self.command)
            selected_time = '2026-01-02T00:00:00Z' if fault == 'wrong_target' else body['time']
            if fault != 'no_op':
                if self.command == 'DELETE':
                    client.query(f"DELETE FROM measure WHERE time = '{selected_time}' AND item = 'a'")
                else:
                    value = 999.0 if fault == 'wrong_value' else body['value']
                    extra = {'untouched': 999} if fault == 'clobber' else {}
                    client.write_points([point(float(value), selected_time, **extra)])
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        do_POST = do_PUT = do_PATCH = do_DELETE = call

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    passed, detected, unverified = 0, 0, 0
    try:
        for method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            action = {'POST': 'insert', 'PUT': 'update', 'PATCH': 'update', 'DELETE': 'delete'}[method]
            operation = {'operationId': 'mutate', 'responses': {'200': {'description': 'OK', 'content': {'application/json': {'schema': {
                'type': 'object', 'required': ['ok'], 'properties': {'ok': {'type': 'boolean'}}}}}}}}
            spec = tmp_path / 'api.json'
            spec.write_text(json.dumps({'openapi': '3.1.0', 'paths': {'/measure': {method.lower(): operation}}}))
            form = {'operation': {'operationId': 'mutate', 'path': '/measure', 'method': method},
                    'name': f'{method}ポイント変更', 'engine': 'influxdb', 'table': 'measure', 'influxAction': action,
                    'influxStatus': 200, 'influxTime': when, 'influxTags': {'item': 'a'}, 'influxFields': {'value': 2.0},
                    'influxPreserve': True, 'requestBody': {'time': when, 'value': 2.0, 'item': 'a'}}
            result = subprocess.run(['node', '--input-type=module', '-e',
                "import {buildDbScenarios} from './gui-tauri/src/db-scenario-editor.js'; console.log(JSON.stringify(buildDbScenarios(JSON.parse(process.argv[1]))));",
                json.dumps(form)], cwd=ROOT, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            scenarios = json.loads(result.stdout)
            # Use the same Python validation/save bridge as the UI.
            sys.path.insert(0, str(ROOT))
            from gui.tauri_bridge import _save_db_scenario_yaml
            scenario_path = tmp_path / 'scenarios.yaml'
            _save_db_scenario_yaml(str(scenario_path), scenarios)
            assert yaml.safe_load(scenario_path.read_text(encoding='utf-8'))['scenarios']['list'][0]['influx_mutation']['action'] == action
            faults = ['correct', 'no_op', 'wrong_target']
            if method != 'DELETE': faults.append('wrong_value')
            if method in ['PUT', 'PATCH']: faults.append('clobber')
            for fault in [*faults, 'bad_precondition']:
                client.query('DROP MEASUREMENT measure')
                if (method != 'POST' and fault != 'bad_precondition') or (method == 'POST' and fault == 'bad_precondition'):
                    client.write_points([point(1.0, untouched=7)])
                before_calls = len(calls)
                label = f'{method}-{fault}'
                run = subprocess.run([sys.executable, str(ROOT / 'runner/db_scenario_runner.py'), str(scenario_path), str(spec),
                                      '--base-url', f'http://127.0.0.1:{server.server_port}', '--config', str(config_path), '--skip-health-check',
                                      '--report-output', str(output / f'{label}.xlsx'), '--evidence-output', str(output / f'{label}.json')],
                                      capture_output=True, text=True)
                expected_code = 0 if fault == 'correct' else 2 if fault == 'bad_precondition' else 1
                assert run.returncode == expected_code, run.stdout + run.stderr
                if fault == 'bad_precondition':
                    assert len(calls) == before_calls
                    unverified += 1
                else:
                    evidence = json.loads((output / f'{label}.json').read_text())['cases'][0]
                    assert evidence['influx_mutation']['verdict'] == ('OK' if fault == 'correct' else 'NG')
                    if fault == 'correct': passed += 1
                    else: detected += 1
        (output / 'summary.json').write_text(json.dumps({'passed': passed, 'faults_detected': detected, 'unverified_without_http': unverified, 'http_calls': len(calls)}, indent=2))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        client.drop_database(config['database']); client.close()
