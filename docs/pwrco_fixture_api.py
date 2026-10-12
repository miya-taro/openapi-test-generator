"""Isolated real PostgreSQL/HTTP fixture for the confirmed pwrco contract."""
import copy
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid

import psycopg2


class PwrcoFixture:
    def __init__(self,config):
        self.config=config;self.table='otg_pwrco_'+uuid.uuid4().hex[:12];self.site_table=self.table+'_site'
        self.calls=[];self.fault=None
        with psycopg2.connect(**config) as conn,conn.cursor() as cur:
            cur.execute(f'CREATE TABLE {self.site_table} (location_id text PRIMARY KEY,site_id integer)')
            cur.execute(f'INSERT INTO {self.site_table} VALUES (%s,101),(%s,202)',('HOME','OTHER'))
            cur.execute(f'CREATE TABLE {self.table} (site_id integer,datetime timestamptz,rate numeric,"start" timestamptz,"end" timestamptz,type integer,PRIMARY KEY(site_id,datetime))')
            cur.execute(f'INSERT INTO {self.table} VALUES (999,%s,42,%s,%s,NULL)',('2000-01-01T00:00:00Z',)*3)
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));fixture.calls.append(copy.deepcopy(body))
                if not fixture.valid(body):
                    if fixture.fault=='partial-write':fixture.insert({**body,'schedule':body['schedule'][:1]})
                    if fixture.fault=='error-write':
                        with psycopg2.connect(**fixture.config) as conn,conn.cursor() as cur:cur.execute(f'UPDATE {fixture.table} SET rate=rate+1 WHERE site_id=999')
                    status=400
                else:
                    try:fixture.insert(body);status=200
                    except psycopg2.Error:status=500
                if fixture.fault=='status':status=201
                payload=b'{}' if fixture.fault=='body' else b''
                self.send_response(status);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    @staticmethod
    def valid(body):
        def timestamp(value):
            try:return isinstance(value,str) and datetime.fromisoformat(value.replace('Z','+00:00')).tzinfo is not None
            except ValueError:return False
        if not isinstance(body,dict) or not any(k in body for k in ['site_id','location_id']):return False
        if 'site_id' in body and type(body['site_id']) is not int:return False
        if 'location_id' in body and not isinstance(body['location_id'],str):return False
        if 'type' in body and (type(body['type']) is not int or body['type'] not in [1,2]):return False
        if not all(timestamp(body.get(k)) for k in ['start_datetime','end_time']):return False
        rows=body.get('schedule')
        return isinstance(rows,list) and bool(rows) and all(isinstance(r,dict) and timestamp(r.get('time')) and type(r.get('value')) in (int,float) for r in rows)

    def insert(self,body):
        with psycopg2.connect(**self.config) as conn,conn.cursor() as cur:
            if 'site_id' in body and self.fault!='priority':site=body['site_id']
            else:cur.execute(f'SELECT site_id FROM {self.site_table} WHERE location_id=%s',(body['location_id'],));site=cur.fetchone()[0]
            rows=copy.deepcopy(body['schedule'])
            if self.fault=='missing':rows.pop()
            if self.fault=='extra':rows.append({'time':(datetime.fromisoformat(rows[-1]['time'])+timedelta(minutes=15)).isoformat(),'value':77})
            if self.fault=='duplicate-value' and len(rows)>1:rows[1]['value']=rows[0]['value']
            if self.fault=='modify-old':cur.execute(f'UPDATE {self.table} SET rate=rate+1 WHERE site_id=999')
            if self.fault=='delete-old':cur.execute(f'DELETE FROM {self.table} WHERE site_id=999')
            for row in rows:
                value=row['value']+1 if self.fault=='rate' else row['value']
                start=body['end_time'] if self.fault=='start' else body['start_datetime']
                end=body['start_datetime'] if self.fault=='end' else body['end_time']
                kind=0 if self.fault=='type' else body.get('type')
                stamp=(datetime.fromisoformat(row['time'])+timedelta(minutes=1)).isoformat() if self.fault=='datetime' else row['time']
                cur.execute(f'INSERT INTO {self.table} VALUES (%s,%s,%s,%s,%s,%s)',(site,stamp,value,start,end,kind))

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        with psycopg2.connect(**self.config) as conn,conn.cursor() as cur:
            cur.execute(f'DROP TABLE {self.table}');cur.execute(f'DROP TABLE {self.site_table}')
