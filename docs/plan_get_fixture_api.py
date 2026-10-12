"""Disposable API with independent Python selection, not the expected SQL."""
import copy
import json
import threading
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import Json, RealDictCursor

QUANTITIES = ['buy','sell','charge','discharge','soc','gen','suppression']


class PlanGetFixture:
    def __init__(self, config):
        self.config = config
        suffix=uuid.uuid4().hex[:12]
        self.table='otg_get_plan_'+suffix
        self.site_table='otg_get_site_'+suffix
        self.setting_table='otg_get_setting_'+suffix
        self.fault=None
        self.calls=[]
        with psycopg2.connect(**config) as conn, conn.cursor() as cur:
            cur.execute(f'CREATE TABLE {self.site_table} (location_id text PRIMARY KEY, site_id integer)')
            cur.execute(f'INSERT INTO {self.site_table} VALUES (%s,101),(%s,202)', ('HOME','OTHER'))
            cur.execute(f'CREATE TABLE {self.setting_table} (site_id integer, setting_id integer, datetime timestamptz, param jsonb)')
            cur.execute(f'INSERT INTO {self.setting_table} VALUES (101,2,now(),%s),(202,2,now(),%s)', (Json({'multiuse':{'use_id':'1-1'}}),Json({'multiuse':{'use_id':'1-1'}})))
            cur.execute(f'''CREATE TABLE {self.table} (datetime timestamptz,created timestamptz,site_id integer,use_id text,
                correct boolean,force boolean,fixed boolean,cpbs_type integer,profit integer,
                {','.join(k+' numeric(15,3)' for k in QUANTITIES)},correct_point jsonb,
                PRIMARY KEY(datetime,created,site_id,use_id))''')
            start=datetime.fromisoformat('2026-10-12T00:00:00+09:00')
            for site in [101,202]:
                for offset in [0,0.5,24,24.5,48]:
                    stamp=start+timedelta(hours=offset)
                    for kind in ['1-1','2-1']:
                        for version in [0,1,2]:
                            val=site+offset+version/10+(10 if kind=='2-1' else 0)
                            row=[stamp,start+timedelta(seconds=version),site,kind,version==1,False,kind=='2-1',0,
                                 10 if offset<24 else 20,*[val+i for i in range(7)],Json({'start_time':'00:00','start':{'buy':val}})]
                            cur.execute(f'INSERT INTO {self.table} VALUES ({",".join(["%s"]*len(row))})',row)
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_): pass
            def do_GET(self):
                request=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
                fixture.calls.append(request)
                try:
                    result=fixture.response(request)
                    payload=json.dumps(result).encode(); self.send_response(200)
                except Exception as exc:
                    payload=json.dumps({'error':str(exc)}).encode(); self.send_response(400)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'

    def response(self, request):
        with psycopg2.connect(**self.config) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if 'site_id' in request and self.fault!='site': site=request['site_id']
            else:
                cur.execute(f'SELECT site_id FROM {self.site_table} WHERE location_id=%s',(request['location_id'],));site=cur.fetchone()['site_id']
            cur.execute(f'SELECT * FROM {self.table} WHERE site_id=%s',(site,));rows=[dict(r) for r in cur.fetchall()]
            cur.execute(f'SELECT * FROM {self.setting_table} WHERE site_id=%s AND setting_id=2 ORDER BY datetime DESC',(site,));settings=cur.fetchall()
        start,end=map(datetime.fromisoformat,[request['start'],request['end']])
        rows=[r for r in rows if start<=r['datetime']<end and ('correct' not in request or request['correct']==r['correct'])]
        def priority(row):
            rank=(1000+row['cpbs_type'] if row['cpbs_type'] is not None else 500) if row['fixed'] else (100 if row['cpbs_type'] is None else 0)
            return (row['correct'] or row['force'],rank,row['created'])
        chosen={}
        for row in rows:
            key=(row['datetime'],row['use_id'])
            if key not in chosen or (row['created']>chosen[key]['created'] if self.fault=='history' else priority(row)>priority(chosen[key])): chosen[key]=row
        candidates=list(chosen.values());fixed=sorted([r for r in candidates if r['fixed'] or r['force']],key=lambda r:(-r['created'].timestamp(),r['use_id']))
        kind=request.get('type') or (fixed[0]['use_id'] if fixed else settings[0]['param']['multiuse']['use_id'])
        rows=sorted([r for r in candidates if r['use_id']==kind or self.fault=='type'],key=lambda r:(r['datetime'],r['use_id']))
        plans={}
        for row in rows:
            local=row['datetime'].astimezone(ZoneInfo('Asia/Tokyo'));day=local.date().isoformat()
            key=(day,row['use_id'])
            plan=plans.setdefault(key,{'date':day,'profit':row['profit'],'type':row['use_id'],'controls':[]})
            plan['controls'].append({'time':local.strftime('%H:%M'),'correct':row['correct'],**{k:float(row[k]) for k in QUANTITIES},'correct_point':row['correct_point']})
        result={'site_id':site,'start_datetime':request['start'],'end_datetime':request['end'],'plans':list(plans.values())}
        if result['plans']:
            controls=result['plans'][0]['controls']
            if self.fault=='missing': controls.pop()
            if self.fault=='extra': controls.append(copy.deepcopy(controls[0]))
            if self.fault=='duplicate': controls[-1]=copy.deepcopy(controls[0])
            if self.fault=='value': controls[0]['buy']+=1
            if self.fault=='json': controls[0]['correct_point']['start']['buy']+=1
            if self.fault=='profit': result['plans'][0]['profit']+=1
            if self.fault=='group': result['plans'][0]['controls'],result['plans'][1]['controls']=result['plans'][1]['controls'],controls
            if self.fault=='split': result['plans'].append(copy.deepcopy(result['plans'][0]))
            if self.fault=='order': result['plans'].reverse();[p['controls'].reverse() for p in result['plans']]
        return result

    def definition(self):
        from pathlib import Path
        raw=json.loads((Path(__file__).parents[1]/'examples/plan-get/scenario.json').read_text())['scenarios'][0]
        sql=raw['db_sql_response_check']['sql']
        for original,replacement in [('h_plan',self.table),('h_setting',self.setting_table),('t_site',self.site_table)]: sql=sql.replace(original,replacement)
        raw['db_sql_response_check']['sql']=sql
        return raw

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        with psycopg2.connect(**self.config) as conn, conn.cursor() as cur:
            for table in [self.table,self.site_table,self.setting_table]: cur.execute(f'DROP TABLE {table}')
