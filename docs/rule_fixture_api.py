"""Independent HTTP API used to verify rule generation against disposable real DBs."""
import json
from pathlib import Path
import subprocess
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import uuid

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from influxdb import InfluxDBClient


def timestamp(value):
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


class RuleFixture:
    def __init__(self, engine, config):
        self.engine, self.config = engine, dict(config)
        self.table = 'otg_rule_' + uuid.uuid4().hex[:12]
        self.calls, self.fault = [], None
        if engine == 'postgres':
            with closing(psycopg2.connect(**config)) as conn, conn.cursor() as cur:
                cur.execute(sql.SQL('CREATE TABLE {} (site text NOT NULL, datetime timestamptz NOT NULL, value numeric NOT NULL, priority integer DEFAULT 0, PRIMARY KEY(site,datetime))').format(sql.Identifier(self.table)))
                conn.commit()
        else:
            self.config['database'] = self.table
            with closing(InfluxDBClient(**self.config)) as client:
                client.create_database(self.table)
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')
                fixture.calls.append(body)
                status = 200
                rows = fixture.rows(body.get('site', 'test'))
                if self.path == '/range':
                    lo, hi = timestamp(body['start']), timestamp(body['end'])
                    rows = [row for row in rows if (timestamp(row['datetime']) > lo if fixture.fault == 'exclude-start' else timestamp(row['datetime']) >= lo)
                            and (timestamp(row['datetime']) <= hi if fixture.fault == 'include-end' else timestamp(row['datetime']) < hi)]
                elif self.path == '/rank':
                    rows = sorted(rows, key=lambda row: row['priority'], reverse=fixture.fault != 'wrong-priority')[:1]
                elif self.path == '/combo':
                    if not ('site' in body or 'location' in body) or (('start' in body) != ('end' in body)):
                        status = 200 if fixture.fault == 'accept-invalid' else 400
                if fixture.fault == 'drop-rows':
                    rows = []
                if fixture.fault == 'duplicate' and rows:
                    rows.append(rows[0])
                if fixture.fault == 'wrong-value' and rows:
                    rows[0] = {**rows[0], 'value': 99}
                if self.path == '/empty400' and not rows:
                    status = 200 if fixture.fault == 'wrong-empty-status' else 400
                response = {'data': [{'value': float(row['value'])} for row in rows]}
                payload = json.dumps(response).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def rows(self, site):
        if self.engine == 'postgres':
            with closing(psycopg2.connect(**self.config)) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql.SQL('SELECT * FROM {} WHERE site=%s').format(sql.Identifier(self.table)), (site,))
                return [dict(row) for row in cur.fetchall()]
        with closing(InfluxDBClient(**self.config)) as client:
            # Query all fixture rows; API filters independently of the tool's query generator.
            return [{**row, 'datetime': row['time']} for row in client.query(f'SELECT * FROM "{self.table}"').get_points() if row.get('site') == site]

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        if self.engine == 'postgres':
            with closing(psycopg2.connect(**self.config)) as conn, conn.cursor() as cur:
                cur.execute(sql.SQL('DROP TABLE {}').format(sql.Identifier(self.table))); conn.commit()
        else:
            with closing(InfluxDBClient(**self.config)) as client:
                client.drop_database(self.config['database'])


def operation(kind='boundary'):
    return {'operationId': 'ruleRead', 'method': 'GET', 'requestSchema': {
        'type': 'object', 'properties': {'site': {'type': 'string'}, 'location': {'type': 'string'},
        'start': {'type': 'string', 'format': 'date-time'}, 'end': {'type': 'string', 'format': 'date-time'},
        'correct': {'type': 'boolean'}, 'type': {'type': 'integer', 'enum': [1, 2]}}}}


def contract(kind='boundary', empty_status=200):
    path = {'boundary': '/range', 'priority': '/rank', 'empty': '/empty400' if empty_status == 400 else '/empty', 'combinations': '/combo'}[kind]
    response_schema = {'type': 'object', 'required': ['data'], 'properties': {
        'data': {'type': 'array', 'items': {'type': 'object', 'required': ['value'],
                                         'properties': {'value': {'type': 'number'}}}}}}
    responses = {str(code): {'description': 'explicit outcome', 'content': {
        'application/json': {'schema': response_schema}}} for code in (200, 400)}
    return {'openapi': '3.0.3', 'info': {'title': 'Rule verification API', 'version': '1'},
            'paths': {path: {'get': {'operationId': 'ruleRead', 'requestBody': {
                'required': True, 'content': {'application/json': {'schema': operation()['requestSchema']}}},
                'responses': responses}}}}



def rule_input(fixture, kind='boundary', empty_status=200):
    time_column = 'datetime' if fixture.engine == 'postgres' else 'time'
    source = {'name': '共通ルール検証', 'request': {'operationId': 'ruleRead', 'body': {
        'site': 'test', 'start': '2026-01-01T00:00:00Z', 'end': '2026-01-02T00:00:00Z'}}, 'response_check': {'expect': {'status': 200}}}
    form = {'kind': kind, 'status': empty_status if kind == 'empty' else 200, 'engine': fixture.engine, 'table': fixture.table,
            'scope': [{'name': 'site', 'type': 'string', 'value': 'test'}],
            'seed': [{'name': 'priority', 'type': 'integer', 'value': '0'}],
            'markerColumn': 'value', 'timeColumn': time_column, 'responseArray': 'data', 'responseField': 'value',
            'stepMs': 1000, 'includeStart': True, 'includeEnd': False,
            'startField': {'source': 'body', 'name': 'start'}, 'endField': {'source': 'body', 'name': 'end'}}
    if kind == 'priority':
        form['candidates'] = [[{'name': time_column, 'type': 'string', 'value': f'2026-01-01T0{i}:00:00Z'},
                               {'name': 'priority', 'type': 'integer', 'value': str(3-i)}] for i in range(3)]
    if kind == 'combinations':
        form['useFixture'] = True
        form['seed'] += [{'name': time_column, 'type': 'string', 'value': '2026-01-01T12:00:00Z'},
                         {'name': 'value', 'type': 'float', 'value': '10'}]
        form['fields'] = [{'source': 'body', 'name': name, 'values': [value], 'omit': True}
                          for name, value in [('site', 'test'), ('location', 'A'), ('start', '2026-01-01T00:00:00Z'), ('end', '2026-01-02T00:00:00Z')]]
        form['relations'] = [{'kind': 'atLeastOne', 'a': 0, 'b': 1}, {'kind': 'together', 'a': 2, 'b': 3}]
        form['invalidStatus'] = 400
        scope = {'table': fixture.table, 'columns': [time_column, 'site', 'value', 'priority'], 'where': {'site': 'test'}}
        if fixture.engine == 'influxdb':
            scope.update(engine='influxdb', time_start='2026-01-01T00:00:00Z', time_end='2026-01-02T00:00:00Z')
        form['unchanged'] = [scope]
    return {'source': source, 'operation': operation(kind), 'form': form}

def generate(data):
    result = subprocess.run(['node', '--input-type=module', '-e', "import {buildRuleCases} from './gui-tauri/src/rule-cases.js'; let s='';for await(const c of process.stdin)s+=c;const x=JSON.parse(s);console.log(JSON.stringify(buildRuleCases(x.source,x.operation,x.form)));"], cwd=Path(__file__).resolve().parents[1], input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, check=True)
    return json.loads(result.stdout)
