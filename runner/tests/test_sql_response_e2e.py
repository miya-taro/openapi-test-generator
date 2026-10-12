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

from docs.plan_get_fixture_api import PlanGetFixture
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from db_backends.sql_response import read_rows
from db_backends.postgres_backend import DBResponseCheckUnverified
from src.parser import parse_openapi

ROOT=Path(__file__).parents[2]


@pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'),reason='requires dedicated PostgreSQL')
def test_sql_nested_get_real_api_and_mutants(tmp_path):
    config=json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']);fixture=PlanGetFixture(config)
    output=Path(os.environ.get('OTG_SQL_EVIDENCE_DIR',str(tmp_path/'evidence')));output.mkdir(parents=True,exist_ok=True)
    try:
        raw=fixture.definition();spec=ROOT/'examples/plan-get/openapi.json';api=parse_openapi(str(spec))
        def run(name,definition,expected=True):
            scenario=parse_scenarios(yaml.safe_dump({'scenarios':[definition]}))[0];evidence={}
            with requests.Session() as session: result=_run_scenario(scenario,api,fixture.url,{'postgres':config},{},session,evidence=evidence)
            (output/f'{name}.json').write_text(json.dumps(_safe_evidence(evidence),ensure_ascii=False,indent=2))
            assert result[0] is expected,result
            return evidence
        for variant,body in [('both',raw['request']['body']),('site',{k:v for k,v in raw['request']['body'].items() if k!='location_id'}),
                             ('location',{**{k:v for k,v in raw['request']['body'].items() if k!='site_id'},'location_id':'HOME'}),
                             ('correct-false',{**raw['request']['body'],'correct':False}),('correct-true',{**raw['request']['body'],'correct':True}),
                             ('type',{**raw['request']['body'],'type':'1-1'})]:
            case=copy.deepcopy(raw);case['request']['body']=body;evidence=run(variant,case)
            assert evidence['db_sql_response_comparison']['row_count']==4
            assert fixture.calls[-1]==body
            result=evidence['response']['body']
            assert result['site_id']==101 and len(result['plans'])==2
            assert result['plans'][0]['type']==('1-1' if variant=='type' else '2-1')
            assert result['plans'][0]['controls'][0]['buy']==(101.1 if variant=='type' else 111.2 if variant=='correct-false' else 111.1)
        for fault in ['site','history','type','missing','extra','duplicate','value','json','profit','group','split']:
            fixture.fault=fault;run(fault,raw,False)
        fixture.fault='order';run('unordered',raw)
        case=copy.deepcopy(raw);case['db_sql_response_check']['arrays'][0]['ordered']=True;run('ordered-reject',case,False)
        fixture.fault=None
        with psycopg2.connect(**config) as conn, conn.cursor() as cur: cur.execute(f'UPDATE {fixture.table} SET fixed=false')
        evidence=run('settings-fallback',raw)
        assert evidence['response']['body']['plans'][0]['type']=='1-1'
        # Readonly transaction rejects writes even inside an otherwise SELECT-shaped statement.
        check=copy.deepcopy(raw['db_sql_response_check']);check['sql']=f'WITH x AS (DELETE FROM {fixture.table} RETURNING *) SELECT * FROM x'
        with pytest.raises(psycopg2.Error): read_rows(check,{'body':raw['request']['body']},{'postgres':config})
        # Request values remain data, including a malicious-looking string.
        case=copy.deepcopy(raw);case['request']['body']['type']="1-1'; DELETE FROM h_plan; --"
        before=len(fixture.calls);run('unknown-type-no-silent-pass',case,False);assert len(fixture.calls)==before
        check=copy.deepcopy(raw['db_sql_response_check']);check['sql']='SELECT 1 AS x, 2 AS x'
        with pytest.raises(ValueError,match='重複'): read_rows(check,{'body':raw['request']['body']},{'postgres':config})
        limit_check={'sql':'SELECT generate_series(1,5001) AS value', 'fields':{'rows[].value':'value'}, 'arrays':[{'path':'rows[]','group_by':[]}]}
        with pytest.raises(DBResponseCheckUnverified,match='5000'): read_rows(limit_check,{}, {'postgres':config})
        scenario=tmp_path/'scenario.yaml';scenario.write_text(yaml.safe_dump({'scenarios':[raw]}));cfg=tmp_path/'config.json';cfg.write_text(json.dumps({'postgres':config}))
        result=subprocess.run([sys.executable,str(ROOT/'runner/db_scenario_runner.py'),str(scenario),str(spec),'--base-url',fixture.url,'--config',str(cfg),'--skip-health-check','--report-output',str(output/'result.xlsx'),'--junit-xml',str(output/'result.xml'),'--evidence-output',str(output/'evidence.json')],capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        assert (output/'result.xlsx').is_file() and (output/'result.xml').is_file()
    finally: fixture.close()
