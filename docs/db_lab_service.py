"""Independent real-DB HTTP service for repeatable tester qualification.

No application schema validator, SQL builder or expected-value mapper is used here.
Only listens on loopback. Each instance owns uniquely named disposable resources.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
from urllib.parse import urlsplit
import uuid

from influxdb import InfluxDBClient
import psycopg2
from psycopg2.extras import Json, RealDictCursor


class DatabaseLab:
    def __init__(self, config, port=0):
        self.config = copy.deepcopy(config)
        suffix = uuid.uuid4().hex[:12]
        self.records = 'otg_lab_records_' + suffix
        self.sites = 'otg_lab_sites_' + suffix
        self.config['influxdb']['database'] = 'otg_lab_' + suffix
        self.influx = InfluxDBClient(**self.config['influxdb'])
        self.token = 'lab-' + uuid.uuid4().hex
        self.calls = []
        self.fault = None
        self.errors = []
        self.sql(f'CREATE TABLE {self.records} (id integer PRIMARY KEY, name text NOT NULL, '
                 'amount numeric(15,3) NOT NULL, enabled boolean NOT NULL, meta jsonb, note text)')
        self.sql(f'CREATE TABLE {self.sites} (location_id text, site_id integer)')
        self.sql(f"INSERT INTO {self.sites} VALUES ('A',11),('B',22),('MULTI',11),('MULTI',22)")
        self.influx.create_database(self.config['influxdb']['database'])
        self.reset()
        lab = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def call(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                try:
                    body = json.loads(raw) if raw else {}
                    path = urlsplit(self.path).path
                    authorized = self.headers.get('auth-key') == lab.token
                    lab.calls.append({'method': self.command, 'path': path, 'authenticated': authorized})
                    if path == '/v1/auth/login' and self.command == 'POST':
                        if body == {'username': 'fixture-user', 'password': 'fixture-password-only'}:
                            status, result = 200, {'id': lab.token, 'created_datetime': datetime.now(timezone.utc).isoformat()}
                        else:
                            status, result = 401, {'error': 'invalid login'}
                    elif not authorized:
                        if lab.fault == 'auth-write':
                            lab.sql(f'UPDATE {lab.records} SET amount=amount+1 WHERE id=99')
                        status, result = 401, {'error': 'unauthorized'}
                    elif path == '/v1/measurements/get' and self.command == 'GET':
                        status, result = lab.measurements(body)
                    elif path == '/v1/point' and self.command in {'POST', 'PUT', 'PATCH', 'DELETE'}:
                        status, result = lab.point(self.command, body)
                    elif path == '/v1/records' or path.startswith('/v1/records/'):
                        status, result = lab.record(self.command, path, body)
                    else:
                        status, result = 404, {'error': 'route not found'}
                except (ValueError, KeyError, TypeError):
                    status, result = 400, {'error': 'invalid input'}
                except Exception as exc:
                    lab.errors.append(type(exc).__name__ + ': ' + str(exc))
                    status, result = 500, {'error': 'internal fixture error'}
                data = b'' if result is None else json.dumps(result, ensure_ascii=False).encode()
                self.send_response(status)
                if result is not None:
                    self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = call

        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def sql(self, query, args=(), fetch=False):
        with psycopg2.connect(**self.config['postgres']) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, args)
                return [dict(row) for row in cursor.fetchall()] if fetch else None

    def reset(self):
        self.sql(f'TRUNCATE {self.records}')
        for row in [(1, '日本語', 1.125, True, {'tags': ['a', 'b']}, None),
                    (2, 'second', -2.5, True, {'nested': {'n': 0}}, 'keep'),
                    (99, 'sentinel', 99.0, True, {}, 'untouched')]:
            self.sql(f'INSERT INTO {self.records} VALUES (%s,%s,%s,%s,%s,%s)', (*row[:4], Json(row[4]), row[5]))
        self.influx.query('DROP MEASUREMENT readings')
        self.influx.query('DROP MEASUREMENT points')
        self.influx.write_points([
            {'measurement': 'readings', 'tags': {'site_id': str(site), 'item': item},
             'time': f'2026-01-0{day}T00:00:00Z', 'fields': {'value': float(site + day)}}
            for site in (11, 22, 99) for item in ('temp', 'humidity', 'other') for day in range(1, 6)])

    @staticmethod
    def valid_record(body, partial=False):
        if not isinstance(body, dict) or not body:
            return False
        required = ('id', 'name', 'amount', 'enabled')
        if not partial and not all(key in body for key in required):
            return False
        rules = {
            'id': lambda v: type(v) is int and v > 0,
            'name': lambda v: isinstance(v, str) and 1 <= len(v) <= 40,
            'amount': lambda v: type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1000,
            'enabled': lambda v: type(v) is bool,
            'meta': lambda v: v is None or isinstance(v, dict),
            'note': lambda v: v is None or isinstance(v, str),
        }
        return all(key in rules and rules[key](value) for key, value in body.items())

    def record(self, method, path, body):
        identifier = int(path.rsplit('/', 1)[1]) if path != '/v1/records' else None
        if method == 'GET':
            rows = self.sql(f'SELECT * FROM {self.records}' + (' WHERE id=%s' if identifier else '') + ' ORDER BY id DESC',
                            (identifier,) if identifier else (), fetch=True)
            for row in rows:
                row['amount'] = float(row['amount'])
            if self.fault == 'read-value' and rows:
                rows[0]['amount'] += 1
            if self.fault == 'read-missing' and rows:
                rows.pop()
            if self.fault == 'read-duplicate' and rows:
                rows.append(copy.deepcopy(rows[0]))
            if identifier:
                return (200, rows[0]) if rows else (404, {'error': 'not found'})
            return 200, {'data': rows}
        if method in {'POST', 'PUT', 'PATCH'}:
            if not self.valid_record(body, partial=method == 'PATCH'):
                if self.fault == 'invalid-write':
                    self.sql(f'UPDATE {self.records} SET amount=amount+1 WHERE id=99')
                return 400, {'error': 'invalid record'}
            if identifier is not None and 'id' in body and body['id'] != identifier:
                return 400, {'error': 'id mismatch'}
        if self.fault == 'no-op':
            return (201, {'id': body['id']}) if method == 'POST' else (204, None)
        if method == 'POST':
            try:
                self.sql(f'INSERT INTO {self.records} VALUES (%s,%s,%s,%s,%s,%s)',
                         (body['id'], body['name'], Decimal(str(body['amount'])) + (1 if self.fault == 'write-value' else 0),
                          body['enabled'], Json(body.get('meta')), body.get('note')))
            except psycopg2.errors.UniqueViolation:
                return 409, {'error': 'duplicate'}
            if self.fault == 'extra-write':
                self.sql(f'UPDATE {self.records} SET amount=amount+1 WHERE id=99')
            return 201, {'id': body['id']}
        if identifier is None:
            return 405, {'error': 'method'}
        target = 99 if self.fault == 'wrong-target' else identifier
        if method == 'DELETE':
            self.sql(f'DELETE FROM {self.records} WHERE id=%s', (target,))
            return 204, None
        if method in {'PUT', 'PATCH'}:
            values = {k: v for k, v in body.items() if k != 'id'}
            if method == 'PUT':
                values.update(meta=body.get('meta'), note=body.get('note'))
            if self.fault == 'write-value' and 'amount' in values:
                values['amount'] += 1
            if self.fault == 'clobber':
                values['note'] = 'broken'
            args = [Json(v) if k == 'meta' else v for k, v in values.items()]
            self.sql(f'UPDATE {self.records} SET ' + ','.join(f'{k}=%s' for k in values) + ' WHERE id=%s', (*args, target))
            return 204, None
        return 405, {'error': 'method'}

    def measurements(self, body):
        if not isinstance(body.get('location_id'), str) or not isinstance(body.get('items'), list):
            return 400, {'error': 'invalid filters'}
        start, end = (datetime.fromisoformat(body[k].replace('Z', '+00:00')) for k in ('start', 'end'))
        sites = self.sql(f'SELECT site_id FROM {self.sites} WHERE location_id=%s', (body['location_id'],), fetch=True)
        ids = {str(row['site_id']) for row in sites}
        if self.fault == 'first-site':
            ids = set(sorted(ids)[:1])
        rows = list(self.influx.query('SELECT * FROM readings').get_points())
        # Deliberately independent from the tool's expected InfluxQL filters.
        selected = []
        for row in rows:
            stamp = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            if (row['site_id'] in ids or self.fault == 'ignore-site') and start < stamp <= end and row['item'] in body['items']:
                selected.append({k: row[k] for k in ('time', 'item', 'value')})
        if self.fault == 'read-value' and selected:
            selected[0]['value'] += 1
        if self.fault == 'read-missing' and selected:
            selected.pop()
        if self.fault == 'read-duplicate' and selected:
            selected.append(copy.deepcopy(selected[0]))
        return 200, {'result': list(reversed(selected))}

    def point(self, method, body):
        stamp = datetime.fromisoformat(body['time'].replace('Z', '+00:00')).isoformat()
        if self.fault != 'no-op':
            if method == 'DELETE':
                self.influx.query(f"DELETE FROM points WHERE time='{stamp}' AND item='a'")
            else:
                value = float(body['value']) + (1 if self.fault == 'write-value' else 0)
                self.influx.write_points([{'measurement': 'points', 'time': stamp, 'tags': {'item': 'a'}, 'fields': {'value': value}}])
        return 204, None

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.sql(f'DROP TABLE {self.records}, {self.sites}')
        self.influx.drop_database(self.config['influxdb']['database'])
        self.influx.close()
