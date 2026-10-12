"""Confirmed API matrix, real HTTP/PG, DB no-change and failure detection."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import requests
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from docs.pwrco_suite import build_suite
from docs.pwrco_fixture_api import PwrcoFixture
from db_scenario import parse_scenarios
from db_scenario_runner import _run_scenario, _safe_evidence
from src.parser import parse_openapi

ROOT=Path(__file__).parents[2]
SPEC=ROOT/'examples/pwrco/openapi.json'


def test_pwrco_suite_matches_contract_and_ui_builder():
    suite=build_suite('2026-10-12T00:00:00+09:00')
    assert suite==json.loads((ROOT/'examples/pwrco/scenarios.json').read_text(encoding="utf-8"))
    schema=json.loads(SPEC.read_text(encoding="utf-8"))['paths']['/v1/pwrco/set']['post']['requestBody']['content']['application/json']['schema']
    validator=Draft202012Validator(schema,format_checker=FormatChecker())
    keys=set()
    for i,case in enumerate(suite['scenarios']):
        parse_scenarios(yaml.safe_dump({'scenarios':[case]}))
        body=case['request']['body']
        assert validator.is_valid(body) is (i<18),case['name']
        if i<18:
            for row in body['schedule']:
                key=(101,row['time']);assert key not in keys;keys.add(key)
        else:assert case['response_check']['expect']['status']==400 and case['db_unchanged']
    assert len(suite['scenarios'])==38
    code="""import fs from 'node:fs'; import {buildInsertScenario} from './gui-tauri/src/insert-editor.js';
const input=JSON.parse(fs.readFileSync(0,'utf8'));const op=input.spec.paths['/v1/pwrco/set'].post;
console.log(JSON.stringify(input.cases.map(c=>buildInsertScenario({name:c.name,operation:{...op,method:'POST',requestSchema:op.requestBody.content['application/json'].schema},engine:'postgres',table:c.db_insert_check.table,rowsPath:'schedule[]',primaryKeys:'site_id,datetime',insertStatus:200,emptyBody:true,requestBody:c.request.body,insertMappings:Object.entries(c.db_insert_check.columns).map(([column,rule])=>({column,rule}))}))));"""
    result=subprocess.run(['node','--input-type=module','-e',code],input=json.dumps({'spec':json.loads(SPEC.read_text(encoding="utf-8")),'cases':suite['scenarios'][:18]}),cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
    assert result.returncode==0,result.stderr
    for actual,expected in zip(json.loads(result.stdout),suite['scenarios'][:18],strict=True):
        assert actual['db_insert_check']==expected['db_insert_check']
        assert actual['request']['body']==expected['request']['body']


@pytest.mark.skipif(not os.environ.get('OTG_INTEGRATION_DB_CONFIG'),reason='requires dedicated PostgreSQL')
def test_pwrco_real_matrix_and_faults(tmp_path):
    config=json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']);fixture=PwrcoFixture(config)
    output=Path(os.environ.get('OTG_PWRCO_EVIDENCE_DIR',str(tmp_path/'evidence')));output.mkdir(parents=True,exist_ok=True)
    try:
        suite=build_suite('2026-10-12T00:00:00+09:00',fixture.table,fixture.site_table);api=parse_openapi(str(SPEC))
        def run(name,raw,expected=True):
            evidence={};case=parse_scenarios(yaml.safe_dump({'scenarios':[raw]}))[0]
            with requests.Session() as session:result=_run_scenario(case,api,fixture.url,{'postgres':config},{},session,evidence=evidence)
            (output/f'{name}.json').write_text(json.dumps(_safe_evidence(evidence),ensure_ascii=False,indent=2),encoding="utf-8")
            assert result[0] is expected,result
            assert fixture.calls[-1]==raw['request']['body']
            return evidence
        for i,case in enumerate(suite['scenarios']):
            evidence=run(f'case-{i+1:02}',case)
            assert evidence['response']['status']==(200 if i<18 else 400)
            if i<18:
                added=evidence['db_insert_comparison']['added_rows'];assert len(added)==len(case['request']['body']['schedule'])
                assert all(row['site_id']==101 and row['type']==case['request']['body'].get('type') for row in added)
        fixture.fault='error-write';run('fault-error-write',suite['scenarios'][-1],False)
        for i,fault in enumerate(['priority','missing','extra','duplicate-value','rate','start','end','type','datetime','body','status','modify-old','delete-old']):
            fixture.fault=fault
            fresh=build_suite(f'2027-{i+1:02}-01T00:00:00+09:00',fixture.table,fixture.site_table) if i<12 else build_suite('2028-01-01T00:00:00+09:00',fixture.table,fixture.site_table)
            case=copy.deepcopy(fresh['scenarios'][17]);run('fault-'+fault,case,False)
        fixture.fault=None
        # Separate non-overlapping timestamps for a complete repeat run through the CLI.
        raw=build_suite('2030-01-01T00:00:00+09:00',fixture.table,fixture.site_table)
        path=tmp_path/'scenarios.json';path.write_text(json.dumps(raw),encoding="utf-8");cfg=tmp_path/'config.json';cfg.write_text(json.dumps({'postgres':config}),encoding="utf-8")
        result=subprocess.run([sys.executable,str(ROOT/'runner/db_scenario_runner.py'),str(path),str(SPEC),'--base-url',fixture.url,'--config',str(cfg),'--skip-health-check','--report-output',str(output/'result.xlsx'),'--junit-xml',str(output/'result.xml'),'--evidence-output',str(output/'evidence.json')],capture_output=True,text=True,encoding="utf-8",timeout=90)
        assert result.returncode==0,result.stdout+result.stderr
        assert (output/'result.xlsx').is_file() and (output/'result.xml').is_file()
    finally:fixture.close()
