"""Login -> three existing DB APIs, authentication rejection, and side effects."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg2
import pytest
import requests
import yaml

ROOT = Path(__file__).parents[2]
sys.path[:0] = [str(ROOT/'runner'), str(ROOT)]
from auth_login import perform_login, build_auth_header, load_auth_config
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from docs.authenticated_fixture import AuthenticatedFixture
from docs.login_fixture_api import LoginFixture, TOKEN, PASSWORD
from docs.plan_fixture_api import PlanFixture
from docs.plan_get_fixture_api import PlanGetFixture
from docs.pwrco_fixture_api import PwrcoFixture
from docs.pwrco_suite import build_suite
from src.parser import parse_openapi


def plan_cases(fixture):
    body=json.loads((ROOT/'examples/plan-post-request.json').read_text(encoding='utf-8'))
    script="""import fs from 'node:fs';import {buildInsertScenario,planInsertMappings} from './gui-tauri/src/insert-editor.js';
const input=JSON.parse(fs.readFileSync(0,'utf8'));const spec=JSON.parse(fs.readFileSync('examples/plan-post-openapi.json','utf8'));
const op=spec.paths['/v1/plan/set'].post;const mappings=planInsertMappings();mappings[0].rule.lookup.table=input.site;
console.log(JSON.stringify(buildInsertScenario({operation:{...op,method:'POST',requestSchema:op.requestBody.content['application/json'].schema},engine:'postgres',table:input.table,name:'authenticated plan',rowsPath:'plans[].controls[]',primaryKeys:'datetime,created,site_id,use_id',insertStatus:200,emptyBody:true,requestBody:input.body,insertMappings:mappings})));"""
    result=subprocess.run(['node','--input-type=module','-e',script],input=json.dumps({'table':fixture.table,'site':fixture.site_table,'body':body}),cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert result.returncode==0,result.stderr
    raw=json.loads(result.stdout)
    bodies=[body,{k:v for k,v in body.items() if k!='location_id'},
            {k:v for k,v in body.items() if k!='site_id'},{**body,'force':True,'type':'2-1'}]
    return [{**copy.deepcopy(raw),'request':{**raw['request'],'body':b}} for b in bodies]


def get_cases(fixture):
    raw=fixture.definition();body=raw['request']['body']
    bodies=[body,{k:v for k,v in body.items() if k!='location_id'},
            {**{k:v for k,v in body.items() if k!='site_id'},'location_id':'HOME'},
            {**body,'correct':False},{**body,'correct':True},{**body,'type':'1-1'}]
    return [{**copy.deepcopy(raw),'request':{**raw['request'],'body':b}} for b in bodies]


def snapshot(config,tables):
    with psycopg2.connect(**config) as conn,conn.cursor() as cur:
        result={}
        for table in tables:
            cur.execute(f'SELECT row_to_json(t)::text FROM "{table}" t ORDER BY row_to_json(t)::text')
            result[table]=cur.fetchall()
        return result


@pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'),reason='requires dedicated PostgreSQL')
@pytest.mark.parametrize('kind',['plan-post','plan-get','pwrco'])
def test_three_apis_with_login_and_auth_failures(tmp_path,monkeypatch,kind):
    for key in ['TEST_AUTH_TOKEN','TEST_AUTH_HEADER_NAME','TEST_AUTH_HEADER_VALUE']:
        monkeypatch.delenv(key,raising=False)
    config=json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    cls,spec_file={'plan-post':(PlanFixture,'examples/plan-post-openapi.json'),
                   'plan-get':(PlanGetFixture,'examples/plan-get/openapi.json'),
                   'pwrco':(PwrcoFixture,'examples/pwrco/openapi.json')}[kind]
    fixture=cls(config);login=LoginFixture();gateway=None
    records=[]
    output=Path(os.environ.get('OTG_THREE_AUTH_EVIDENCE_DIR',str(tmp_path/'evidence')))/kind
    output.mkdir(parents=True,exist_ok=True)
    try:
        cases=plan_cases(fixture) if kind=='plan-post' else get_cases(fixture) if kind=='plan-get' else build_suite('2031-01-01T00:00:00+09:00',fixture.table,fixture.site_table)['scenarios']
        api=parse_openapi(str(ROOT/spec_file))
        operation_id=cases[0]['request']['operationId']
        route,method,operation=next((p,m,op) for p,item in api['paths'].items() for m,op in item.items() if isinstance(op,dict) and op.get('operationId')==operation_id)
        operation['responses']['401']={'description':'Provisional fixture auth rejection'}
        operation['security']=[{'sessionId':[]}]
        api.setdefault('components',{}).setdefault('securitySchemes',{})['sessionId']={'type':'apiKey','in':'header','name':'auth-key'}
        spec=tmp_path/'openapi.json';spec.write_text(json.dumps(api),encoding='utf-8')
        gateway=AuthenticatedFixture(login.url,fixture.url,route)
        tables=[fixture.table,fixture.site_table]
        if kind=='plan-get':tables.append(fixture.setting_table)
        scopes=[]
        with psycopg2.connect(**config) as conn,conn.cursor() as cur:
            for table in tables:
                cur.execute(f'SELECT * FROM "{table}" LIMIT 0')
                scopes.append({'table':table,'columns':[c.name for c in cur.description],'where':{}})
        auth=load_auth_config(str(ROOT/'examples/login/auth.json'))
        with requests.Session() as session:
            token=perform_login(gateway.url,auth,session)
            header=build_auth_header(token,auth)
            def run(label,raw,auth_header,expected=True):
                evidence={}
                scenario=parse_scenarios(yaml.safe_dump({'scenarios':[raw]}))[0]
                outcome=_run_scenario(scenario,api,gateway.url,{'postgres':config},{},session,auth_header=auth_header,evidence=evidence)
                assert outcome[0] is expected,(label,outcome)
                safe=_safe_evidence(evidence)
                serialized=json.dumps(safe,ensure_ascii=False,default=str)
                assert TOKEN not in serialized and PASSWORD not in serialized
                (output/f'{label}.json').write_text(serialized,encoding='utf-8')
                records.append({'name':label,'expected_tool_pass':expected,'actual_tool_pass':outcome[0],'http_status':evidence['response']['status']})
                return evidence
            for index,raw in enumerate(cases):
                run(f'valid-auth-{index+1:02}',raw,header)
                assert gateway.calls[-1]['authenticated'] is True
            # Fresh keys let a write-before-auth bug remain observable on INSERT-only APIs.
            fresh=copy.deepcopy(cases[0]) if kind!='pwrco' else build_suite('2033-01-01T00:00:00+09:00',fixture.table,fixture.site_table)['scenarios'][0]
            denied={'name':'authentication rejected','request':fresh['request'],
                    'response_check':{'expect':{'status':401,'empty_body':True}},'db_unchanged':scopes}
            for label,credential in [('missing',None),('invalid',('auth-key','invalid-id'))]:
                before=snapshot(config,tables);calls=len(fixture.calls)
                result=run('auth-'+label,denied,credential)
                assert result['response']['status']==401
                assert len(fixture.calls)==calls
                assert snapshot(config,tables)==before
            gateway.fault='ignore-auth'
            result=run('fault-ignore-auth',denied,None,False)
            assert result['response']['status']==200
            if kind!='plan-get':
                gateway.fault='write-before-deny'
                if kind=='pwrco':
                    denied['request']=build_suite('2034-01-01T00:00:00+09:00',fixture.table,fixture.site_table)['scenarios'][0]['request']
                before=snapshot(config,tables)
                result=run('fault-write-before-401',denied,('auth-key','invalid-id'),False)
                assert result['response']['status']==401
                assert snapshot(config,tables)!=before
            gateway.fault=None
        # Exercise the actual DB runner CLI's own login, not just injected headers.
        raw=copy.deepcopy(cases[0]) if kind!='pwrco' else build_suite('2035-01-01T00:00:00+09:00',fixture.table,fixture.site_table)['scenarios'][0]
        scenario=tmp_path/'scenario.json';scenario.write_text(json.dumps({'scenarios':[raw]}),encoding='utf-8')
        cfg=tmp_path/'db.json';cfg.write_text(json.dumps({'postgres':config}),encoding='utf-8')
        auth_path=tmp_path/'auth.json';auth_path.write_text(json.dumps(auth),encoding='utf-8')
        command=[sys.executable,str(ROOT/'runner/db_scenario_runner.py'),str(scenario),str(spec),'--base-url',gateway.url,'--config',str(cfg),'--auth-config',str(auth_path),'--skip-health-check','--report-output',str(output/'result.xlsx'),'--junit-xml',str(output/'result.xml'),'--evidence-output',str(output/'evidence.json')]
        start=len(gateway.calls)
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        assert [c['login'] for c in gateway.calls[start:]]==[True,False]
        assert gateway.calls[-1]['authenticated'] is True
        auth['body']['password']='wrong-password';auth_path.write_text(json.dumps(auth),encoding='utf-8')
        before=snapshot(config,tables);start=len(gateway.calls)
        failure=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=60)
        assert failure.returncode==3,failure.stdout+failure.stderr
        assert [c['login'] for c in gateway.calls[start:]]==[True]
        assert snapshot(config,tables)==before
        (output/'summary.json').write_text(json.dumps({'api':kind,'cases':records,'cli_login':'passed','cli_login_failure_stops_api':'passed'},ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'{kind}: {len(cases)} existing cases with login, missing/invalid auth, fault detection, CLI passed')
    finally:
        if gateway:gateway.close()
        login.close();fixture.close()
