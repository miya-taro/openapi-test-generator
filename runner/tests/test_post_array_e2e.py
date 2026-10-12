"""Real PostgreSQL + independent HTTP API, UI-generated mappings, mutant detection."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import requests
import yaml

ROOT = Path(__file__).parents[2]
sys.path[:0] = [str(ROOT/'runner'), str(ROOT)]
from docs.plan_fixture_api import PlanFixture
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from src.parser import parse_openapi


@pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires dedicated PostgreSQL')
def test_ui_generated_array_insert_against_postgres_and_mutants(tmp_path):
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    fixture = PlanFixture(config)
    output = Path(os.environ.get('OTG_POST_EVIDENCE_DIR', str(tmp_path/'evidence')))
    output.mkdir(parents=True, exist_ok=True)
    spec = ROOT/'examples/plan-post-openapi.json'
    request = json.loads((ROOT/'examples/plan-post-request.json').read_text())
    code = """import fs from 'node:fs'; import {buildInsertScenario,planInsertMappings} from './gui-tauri/src/insert-editor.js';
const input=JSON.parse(fs.readFileSync(0,'utf8')); const spec=JSON.parse(fs.readFileSync('examples/plan-post-openapi.json','utf8'));
const op=spec.paths['/v1/plan/set'].post; const mappings=planInsertMappings(); mappings[0].rule.lookup.table=input.site_table;
console.log(JSON.stringify(buildInsertScenario({operation:{...op,method:'POST',requestSchema:op.requestBody.content['application/json'].schema},engine:'postgres',table:input.table,name:'plan insert',rowsPath:'plans[].controls[]',primaryKeys:'datetime,created,site_id,use_id',insertStatus:200,emptyBody:true,requestBody:input.body,insertMappings:mappings})));"""
    try:
        result = subprocess.run(['node','--input-type=module','-e',code], input=json.dumps({'table':fixture.table,'site_table':fixture.site_table,'body':request}), cwd=ROOT, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        raw = json.loads(result.stdout)
        api = parse_openapi(str(spec))
        def run(name, definition, expected):
            case = parse_scenarios(yaml.safe_dump({'scenarios':[definition]}))[0]
            evidence = {}
            with requests.Session() as session:
                status = _run_scenario(case, api, fixture.url, {'postgres':config}, {}, session, evidence=evidence)
            (output/f'{name}.json').write_text(json.dumps(_safe_evidence(evidence), ensure_ascii=False, indent=2), encoding='utf-8')
            assert status[0] is expected, status
            return evidence
        for name, body in [('both-site-wins',request),('site-only',{k:v for k,v in request.items() if k!='location_id'}),
                           ('location-only',{k:v for k,v in request.items() if k!='site_id'}),
                           ('force-true',{**request,'force':True,'type':'2-1'})]:
            case = copy.deepcopy(raw); case['request']['body'] = body
            evidence = run(name,case,True)
            assert evidence['db_insert_comparison']['actual_count'] == 4
            assert fixture.calls[-1] == body
        for fault in ('missing','extra','duplicate','none_inserted','numeric','profit','json','datetime','fixed','force','use_id','priority','created','body','modify_old','delete_old'):
            fixture.fault = fault
            evidence = run(fault,raw,False)
            if fault == 'body': assert evidence['response_contract']['verdict'] == 'NG'
            else: assert evidence['db_insert_comparison']['verdict'] == 'NG'
        fixture.fault = None
        scenarios = tmp_path/'scenario.yaml'; scenarios.write_text(yaml.safe_dump({'scenarios':[raw]}))
        cfg = tmp_path/'config.json'; cfg.write_text(json.dumps({'postgres':config}))
        cli = subprocess.run([sys.executable, str(ROOT/'runner/db_scenario_runner.py'), str(scenarios), str(spec), '--base-url', fixture.url,
                              '--config',str(cfg),'--skip-health-check','--report-output',str(output/'result.xlsx'),
                              '--junit-xml',str(output/'result.xml'),'--evidence-output',str(output/'evidence.json')], capture_output=True, text=True, timeout=60)
        assert cli.returncode == 0, cli.stdout+cli.stderr
        assert (output/'result.xlsx').is_file() and (output/'result.xml').is_file()
    finally:
        fixture.close()
