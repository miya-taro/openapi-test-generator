"""Independent, disposable PostgreSQL API for POST array mapping qualification."""
import copy
import json
import math
import re
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2
from psycopg2.extras import Json

QUANTITIES = ('buy', 'sell', 'charge', 'discharge', 'soc', 'gen', 'suppression')


def valid_plan_request(body):
    """Independent checks, deliberately not using the tool's schema/validator."""
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)

    def clock(value):
        return isinstance(value, str) and re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d', value) is not None

    def timestamp(value):
        try:
            return isinstance(value, str) and 'T' in value and datetime.fromisoformat(value).tzinfo is not None
        except ValueError:
            return False

    if not isinstance(body, dict) or not any(key in body for key in ('site_id', 'location_id')):
        return False
    if 'site_id' in body and type(body['site_id']) is not int:
        return False
    if 'location_id' in body and not isinstance(body['location_id'], str):
        return False
    if body.get('type') not in ('1-1', '2-1') or not all(type(body.get(key)) is bool for key in ('correct', 'force')):
        return False
    plans = body.get('plans')
    if not isinstance(plans, list) or not plans:
        return False
    for plan in plans:
        if not isinstance(plan, dict) or not timestamp(plan.get('date')) or type(plan.get('profit')) is not int:
            return False
        controls = plan.get('controls')
        if not isinstance(controls, list) or not controls:
            return False
        for control in controls:
            if not isinstance(control, dict) or not clock(control.get('time')) or not all(number(control.get(key)) for key in QUANTITIES):
                return False
            if 'correct_point' in control:
                point = control['correct_point']
                if not isinstance(point, dict) or ('start_time' in point and not clock(point['start_time'])):
                    return False
                if 'start' in point and (not isinstance(point['start'], dict) or any(
                        key in point['start'] and not number(point['start'][key]) for key in QUANTITIES)):
                    return False
    return True


class PlanFixture:
    def __init__(self, config):
        self.config = config
        self.table = 'otg_plan_' + uuid.uuid4().hex[:12]
        self.site_table = 'otg_site_' + uuid.uuid4().hex[:12]
        self.fault = None
        self.calls = []
        with psycopg2.connect(**config) as conn, conn.cursor() as cur:
            cur.execute(f'CREATE TABLE "{self.site_table}" (location_id text PRIMARY KEY, site_id integer NOT NULL)')
            cur.execute(f'INSERT INTO "{self.site_table}" VALUES (%s,%s),(%s,%s)', ('LOC001', 101, 'LOC002', 202))
            cur.execute(f'''CREATE TABLE "{self.table}" (
                datetime timestamptz NOT NULL, created timestamptz NOT NULL, site_id integer NOT NULL, use_id text NOT NULL,
                manual boolean, fixed boolean, force boolean, cpbs_type integer DEFAULT 0,
                profit numeric(15,3), buy numeric(15,3), sell numeric(15,3), charge numeric(15,3), discharge numeric(15,3),
                soc numeric(15,3), gen numeric(15,3), suppression numeric(15,3), correct_point jsonb,
                PRIMARY KEY (datetime,created,site_id,use_id))''')
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_POST(self):
                try:
                    request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                except ValueError:
                    request = None
                fixture.calls.append(copy.deepcopy(request))
                try:
                    if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json' or not valid_plan_request(request):
                        if fixture.fault == 'partial-write':
                            partial = copy.deepcopy(request)
                            partial['plans'] = [partial['plans'][0]]
                            partial['plans'][0]['controls'] = partial['plans'][0]['controls'][:1]
                            fixture.insert(partial)
                        elif fixture.fault == 'error-write':
                            with psycopg2.connect(**fixture.config) as conn, conn.cursor() as cur:
                                cur.execute(f'UPDATE "{fixture.table}" SET buy=buy+1')
                        if fixture.fault != 'accept-invalid':
                            raise ValueError('invalid input')
                        self.send_response(200)
                        self.send_header('Content-Length', '0')
                        self.end_headers()
                        return
                    fixture.insert(request)
                    self.send_response(200)
                    data = b'{}' if fixture.fault == 'body' else b''
                except (ValueError, KeyError, TypeError, psycopg2.Error):
                    self.send_response(400)
                    data = b''
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def insert(self, request):
        with psycopg2.connect(**self.config) as conn, conn.cursor() as cur:
            if 'site_id' in request and self.fault != 'priority':
                site = request['site_id']
            else:
                cur.execute(f'SELECT site_id FROM "{self.site_table}" WHERE location_id=%s', (request['location_id'],))
                site = cur.fetchone()[0]
            created = datetime.now(ZoneInfo('Asia/Tokyo'))
            if self.fault == 'created':
                created -= timedelta(days=1)
            rows = []
            for plan in request['plans']:
                day = datetime.fromisoformat(plan['date']).astimezone(ZoneInfo('Asia/Tokyo'))
                for control in plan['controls']:
                    hour, minute, second = map(int, control['time'].split(':'))
                    stamp = day.replace(hour=hour, minute=minute, second=second, microsecond=0)
                    cp = copy.deepcopy(control.get('correct_point'))
                    if self.fault == 'json' and cp:
                        cp['start']['buy'] += 100
                    rows.append([stamp, created, site, request['type'], False, False, request['force'], 0, plan['profit'],
                                 *[control[k] for k in ('buy','sell','charge','discharge','soc','gen','suppression')], Json(cp)])
            if self.fault == 'missing': rows.pop()
            if self.fault == 'none_inserted': rows = []
            if self.fault == 'duplicate':
                extra = list(rows[0]); extra[1] += timedelta(milliseconds=1); rows.append(extra)
            if self.fault == 'extra':
                extra = list(rows[0]); extra[2] = 999; rows.append(extra)
            if self.fault == 'fixed': rows[0][5] = True
            if self.fault == 'force': rows[0][6] = not request['force']
            if self.fault == 'profit': rows[-1][8] += 1
            if self.fault == 'numeric': rows[0][9] += 0.001
            if self.fault == 'datetime': rows[0][0] += timedelta(hours=9)
            if self.fault == 'use_id': rows[0][3] = 'wrong'
            if self.fault == 'modify_old': cur.execute(f'UPDATE "{self.table}" SET buy=999')
            if self.fault == 'delete_old': cur.execute(f'DELETE FROM "{self.table}"')
            for row in rows:
                cur.execute(f'INSERT INTO "{self.table}" (datetime,created,site_id,use_id,manual,fixed,force,cpbs_type,profit,buy,sell,charge,discharge,soc,gen,suppression,correct_point) VALUES ({",".join(["%s"] * len(row))})', row)

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        with psycopg2.connect(**self.config) as conn, conn.cursor() as cur:
            cur.execute(f'DROP TABLE "{self.table}"')
            cur.execute(f'DROP TABLE "{self.site_table}"')
