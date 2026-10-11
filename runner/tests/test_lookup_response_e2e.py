"""UI -> lookup (real PostgreSQL) -> real InfluxDB -> GET JSON API + mutants."""
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
import psycopg2
import pytest
import requests
import yaml

ROOT = Path(__file__).parents[2]
sys.path[:0] = [str(ROOT / 'runner'), str(ROOT)]
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from src.parser import parse_openapi


def test_cross_db_lookup_api_and_mutations(tmp_path):
    pg_text = os.environ.get('OTG_INTEGRATION_DB_CONFIG')
    influx_text = os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')
    if not pg_text or not influx_text:
        pytest.skip('requires dedicated PostgreSQL and InfluxDB 1.x')
    pg_config = json.loads(pg_text)
    influx_config = {**json.loads(influx_text), 'database': 'otg_lookup_' + uuid.uuid4().hex[:12]}
    table = 'otg_site_' + uuid.uuid4().hex[:12]
    measure_table = 'otg_measure_' + uuid.uuid4().hex[:12]
    client = InfluxDBClient(**influx_config)
    client.create_database(influx_config['database'])
    config = {'postgres': pg_config, 'influxdb': influx_config}
    output = Path(os.environ.get('OTG_LOOKUP_EVIDENCE_DIR', str(tmp_path / 'evidence')))
    output.mkdir(parents=True, exist_ok=True)
    with psycopg2.connect(**pg_config) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE TABLE "{table}" (location_id text NOT NULL, site_id integer NOT NULL)')
        cur.executemany(f'INSERT INTO "{table}" VALUES (%s, %s)', [('A', 11), ('B', 22), ('MULTI', 11), ('MULTI', 22)])
    points = [dict(measurement='measure', tags={'site_id': str(site), 'item': item},
                   time=f'2026-01-0{day}T00:00:00Z', fields={'value': float(site + day)})
              for site in (11, 22, 99) for item in ('temp', 'humidity', 'other') for day in range(1, 6)]
    client.write_points(points)
    client.write_points([dict(measurement='sites', tags={'location_id': location},
                             time=f'2026-01-01T00:00:0{index}Z', fields={'site_id': site})
                         for index, (location, site) in enumerate([('A', 11), ('B', 22), ('MULTI', 11), ('MULTI', 22)])])
    with psycopg2.connect(**pg_config) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE TABLE "{measure_table}" (site_id integer, time timestamptz, item text, value double precision)')
        cur.executemany(f'INSERT INTO "{measure_table}" VALUES (%s, %s, %s, %s)',
                        [(int(p['tags']['site_id']), p['time'], p['tags']['item'], p['fields']['value']) for p in points])
    mode = 'correct'
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            calls.append(body)
            with psycopg2.connect(**pg_config) as conn, conn.cursor() as cur:
                cur.execute(f'SELECT site_id FROM "{table}" WHERE location_id=%s ORDER BY site_id', (body['location_id'],))
                sites = [str(row[0]) for row in cur.fetchall()]
            if mode == 'wrong_site':
                sites = ['22']
            elif mode == 'first_site':
                sites = sites[:1]
            result = []
            for point in client.query('SELECT * FROM measure').get_points():
                if mode != 'ignore_site' and point['site_id'] not in sites:
                    continue
                if not body['start'] <= point['time'] <= body['end'] or point['item'] not in body['items']:
                    continue
                result.append({k: point[k] for k in ('time', 'item', 'value')})
            if mode == 'wrong_value' and result:
                result[0]['value'] += 1
            if mode == 'missing_row' and result:
                result.pop()
            if mode == 'duplicate_row' and result:
                result.append(dict(result[0]))
            if not sites and mode != 'empty':
                status, response = 404, {'error': 'location not found'}
            else:
                status = 200
                response = {'site_id': int(sites[0]) if sites else 0, 'start': body['start'], 'end': body['end'], 'result': result}
            data = json.dumps(response).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('X-Result-Count', str(len(result)))
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    raw = json.loads((ROOT / 'examples/measure-get-openapi.json').read_text(encoding='utf-8'))
    operation = raw['paths']['/v1/result/measure/get']['get']
    operation['responses']['404'] = copy.deepcopy(operation['responses']['400'])
    spec_path = tmp_path / 'openapi.json'
    spec_path.write_text(json.dumps(raw), encoding='utf-8')
    api = parse_openapi(str(spec_path))
    form = {
        'operation': {'operationId': operation['operationId'], 'method': 'GET', 'path': '/v1/result/measure/get',
                      'requestSchema': operation['requestBody']['content']['application/json']['schema'],
                      'responseSchema': operation['responses']['200']['content']['application/json']['schema'], 'parameters': []},
        'engine': 'influxdb', 'name': 'location lookup', 'table': 'measure',
        'requestBody': {'location_id': 'A', 'start': '2026-01-02T00:00:00Z', 'end': '2026-01-04T00:00:00Z', 'items': ['temp', 'humidity']},
        'responseStatus': '200', 'responseShape': 'array', 'responseArrayPath': 'result',
        'readMappings': [{'source': key, 'target': key} for key in ('time', 'item', 'value')],
        'readFilters': [
            {'source': 'body', 'parameter': 'location_id', 'column': 'site_id', 'operator': '=', 'lookup': {
                'engine': 'postgres', 'table': table, 'match_column': 'location_id', 'value_column': 'site_id',
                'cardinality': 'one', 'value_type': 'string', 'on_empty': 'unverified'}},
            *[{'source': 'body', 'parameter': key, 'column': 'time' if key != 'items' else 'item', 'operator': op}
              for key, op in [('start', '>='), ('end', '<='), ('items', 'in')]],
        ],
    }

    def generate(value):
        script = "import {buildDbScenario} from './gui-tauri/src/db-scenario-editor.js'; import fs from 'node:fs'; console.log(JSON.stringify(buildDbScenario(JSON.parse(fs.readFileSync(0,'utf8')))));"
        result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(value), cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def run(definition, label, expected):
        scenario = parse_scenarios(yaml.safe_dump({'scenarios': [definition]}))[0]
        evidence = {}
        with requests.Session() as session:
            result = _run_scenario(scenario, api, base, config, {}, session, evidence=evidence)
        (output / f'{label}.json').write_text(json.dumps(_safe_evidence(evidence), ensure_ascii=False, indent=2), encoding='utf-8')
        assert result[0] is expected, result
        return result, evidence

    try:
        single = generate(form)
        _, evidence = run(single, 'single', True)
        assert evidence['db_lookups'][0]['values'] == ['11']
        assert len(evidence['db_response_comparison']['expected_rows']) == 6
        assert calls[-1] == form['requestBody'] and 'site_id' not in calls[-1]
        for mode in ('wrong_site', 'ignore_site', 'wrong_value', 'missing_row', 'duplicate_row'):
            run(single, mode, False)
        mode = 'correct'
        many_form = copy.deepcopy(form)
        many_form['requestBody']['location_id'] = 'MULTI'
        many_form['readFilters'][0]['operator'] = 'in'
        many_form['readFilters'][0]['lookup']['cardinality'] = 'many'
        many = generate(many_form)
        _, evidence = run(many, 'many', True)
        assert set(evidence['db_lookups'][0]['values']) == {'11', '22'}
        assert len(evidence['db_response_comparison']['expected_rows']) == 12
        reverse_form = copy.deepcopy(many_form)
        reverse_form.update(engine='postgres', table=measure_table)
        reverse_form['readFilters'][0]['lookup'].update(engine='influxdb', database=influx_config['database'], table='sites', value_type='integer')
        reverse = generate(reverse_form)
        _, reverse_evidence = run(reverse, 'influx-to-postgres', True)
        assert set(reverse_evidence['db_lookups'][0]['values']) == {11, 22}
        assert len(reverse_evidence['db_response_comparison']['expected_rows']) == 12
        mode = 'first_site'
        run(many, 'first-site-only', False)
        mode = 'correct'
        ambiguous = copy.deepcopy(single)
        ambiguous['request']['body']['location_id'] = 'MULTI'
        before = len(calls)
        result, _ = run(ambiguous, 'ambiguous', False)
        assert '[UNVERIFIED]' in result[1] and len(calls) == before
        missing = copy.deepcopy(single)
        missing['request']['body']['location_id'] = 'MISSING'
        result, _ = run(missing, 'missing-unconfigured', False)
        assert '[UNVERIFIED]' in result[1] and len(calls) == before
        missing['db_response_check']['filters'][0]['lookup'].update(on_empty='status', empty_status=404)
        _, evidence = run(missing, 'missing-404', True)
        assert evidence['expected_status'] == 404
        mode = 'empty'
        run(missing, 'missing-wrong-status', False)
        missing['db_response_check']['filters'][0]['lookup']['on_empty'] = 'empty'
        del missing['db_response_check']['filters'][0]['lookup']['empty_status']
        run(missing, 'missing-empty', True)

        # Full CLI execution persists lookup provenance alongside Excel and JUnit.
        mode = 'correct'
        scenario_path = tmp_path / 'lookup.yaml'
        scenario_path.write_text(yaml.safe_dump({'scenarios': [single]}), encoding='utf-8')
        config_path = tmp_path / 'config.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        result = subprocess.run([sys.executable, str(ROOT / 'runner/db_scenario_runner.py'), str(scenario_path), str(spec_path),
                                 '--base-url', base, '--config', str(config_path), '--skip-health-check',
                                 '--report-output', str(output / 'lookup.xlsx'), '--junit-xml', str(output / 'lookup.xml'),
                                 '--evidence-output', str(output / 'lookup-evidence.json')], capture_output=True, text=True, encoding='utf-8', timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (output / 'lookup.xlsx').is_file() and (output / 'lookup.xml').is_file()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        client.drop_database(influx_config['database'])
        client.close()
        with psycopg2.connect(**pg_config) as conn, conn.cursor() as cur:
            cur.execute(f'DROP TABLE "{table}"')
            cur.execute(f'DROP TABLE "{measure_table}"')
