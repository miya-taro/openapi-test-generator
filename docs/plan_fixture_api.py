"""Independent, disposable PostgreSQL API for POST array mapping qualification."""
import copy
import json
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2
from psycopg2.extras import Json


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
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append(copy.deepcopy(request))
                try:
                    fixture.insert(request)
                    self.send_response(200)
                    data = b'{}' if fixture.fault == 'body' else b''
                except (ValueError, KeyError, psycopg2.Error):
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
