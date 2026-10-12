"""Real HTTP login + custom header chain, including deliberately broken APIs."""
import json
import os
import sys
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'runner'))
from docs.login_fixture_api import LoginFixture, PASSWORD, TOKEN, USERNAME
from auth_login import perform_login, build_auth_header, load_auth_config, mark_login_response_sensitive
from http_client import execute_with_openapi
from models import RunCase
from response_schema import from_run_case
from verifier import verify
from src.parser import parse_openapi
from src.extractor import extract_specs, extract_auth_specs
from src.generator import generate_test_cases
from src.id_assigner import assign_ids

SPEC = ROOT / 'examples/login/openapi.json'
AUTH = ROOT / 'examples/login/auth.json'


def run_case(raw):
    return RunCase(*(raw[key] for key in ['id','operationId','path','method','in','paramName','inputValue','expectedStatus','expectedResponseBody','expectedResponseHeader','expectedResponseTime','expectedResult']))


def explicit(case_id, body, status):
    return RunCase(case_id,'login','/v1/auth/login','POST','body','requestBody',json.dumps(body),str(status),'','','','')


@pytest.fixture
def setup(monkeypatch):
    fixture=LoginFixture()
    api=parse_openapi(str(SPEC))
    mark_login_response_sensitive(api,load_auth_config(str(AUTH)))
    with requests.Session() as session:
        token=perform_login(fixture.url,load_auth_config(str(AUTH)),session)
        name,value=build_auth_header(token,load_auth_config(str(AUTH)))
        monkeypatch.setenv('TEST_AUTH_HEADER_NAME',name)
        monkeypatch.setenv('TEST_AUTH_HEADER_VALUE',value)
        try:
            yield fixture,api,session
        finally:
            fixture.close()


def execute(case, setup):
    fixture,api,session=setup
    result=execute_with_openapi(case,fixture.url,api,session)
    verdict,detail=verify(result,from_run_case(case,api))
    return result,verdict,detail


def test_generated_login_contract_and_auth_chain(setup, tmp_path):
    fixture,api,_=setup
    params,bodies=extract_specs(api)
    cases=assign_ids(generate_test_cases(params,bodies,{'includeNormal':True,'includeAbnormal':True},extract_auth_specs(api)))
    results=[]
    for raw in cases:
        # Explicit fixture expectation: an empty credential is a login failure,
        # even though plain OpenAPI string permits the empty string.
        if raw['operationId']=='login' and raw['perspective']=='正常系_空値':
            raw['expectedStatus']='401'
        result,verdict,detail=execute(run_case(raw),setup)
        results.append({'id':raw['id'],'operation':raw['operationId'],'condition':raw['perspective'],'status':result.actual_status,'verdict':verdict})
        assert verdict=='OK',(raw,detail)
    for index,body in enumerate([
        {'username':USERNAME,'password':'wrong'}, {'username':'unknown','password':PASSWORD},
        {'username':'','password':PASSWORD}, {'username':USERNAME,'password':''},
    ]):
        result,verdict,detail=execute(explicit(f'LOGIN-invalid-{index}',body,401),setup)
        assert verdict=='OK',detail
        results.append({'id':result.case.id,'status':result.actual_status,'verdict':verdict})
    assert any(c.get('authenticated') is True for c in fixture.calls)
    assert sum(c.get('authenticated') is False for c in fixture.calls)>=2
    output=Path(os.environ.get('OTG_LOGIN_EVIDENCE_DIR',str(tmp_path)))
    output.mkdir(parents=True,exist_ok=True)
    (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Login/auth-key: {len(results)} cases passed')


@pytest.mark.parametrize('fault',['missing-id','wrong-id-type','missing-date','invalid-date','accept-password','accept-invalid','ignore-auth'])
def test_detects_faulty_login_and_auth(setup,fault):
    fixture,_,_=setup
    fixture.fault=fault
    case=explicit('LOGIN-fault',{'username':USERNAME,'password':PASSWORD},200)
    if fault=='accept-password':case=explicit('LOGIN-fault',{'username':USERNAME,'password':'wrong'},401)
    if fault=='accept-invalid':case=explicit('LOGIN-fault',{'username':USERNAME,'password':None},400)
    if fault=='ignore-auth':
        from src.security_payload import AUTH_NONE_MARKER, OPENAPI_SECURITY_PARAM
        case=RunCase('AUTH-fault','protected','/v1/protected','GET','header',OPENAPI_SECURITY_PARAM,AUTH_NONE_MARKER,'401','','','','')
    _,verdict,detail=execute(case,setup)
    assert verdict=='NG',detail


def test_login_evidence_does_not_expose_credentials(setup):
    result,verdict,_=execute(explicit('LOGIN-evidence',{'username':USERNAME,'password':PASSWORD},200),setup)
    assert verdict=='OK'
    assert PASSWORD not in result.curl_command
    assert TOKEN not in result.report_body


def test_cli_login_contract_evidence(tmp_path):
    import subprocess
    from openpyxl import load_workbook
    from src.renderer.json_output import build_output
    from src.renderer.excel_output import write_excel_output
    api=parse_openapi(str(SPEC))
    params,bodies=extract_specs(api)
    cases=assign_ids(generate_test_cases(params,bodies,{'includeNormal':True,'includeAbnormal':True},extract_auth_specs(api)))
    for raw in cases:
        if raw['operationId']=='login' and raw['perspective']=='正常系_空値':raw['expectedStatus']='401'
    source=tmp_path/'cases.xlsx';result=tmp_path/'result.xlsx'
    write_excel_output(build_output(cases,str(SPEC)),str(source))
    fixture=LoginFixture()
    try:
        completed=subprocess.run([sys.executable,str(ROOT/'runner/runner.py'),str(source),str(SPEC),
            '--base-url',fixture.url,'--auth-config',str(AUTH),'--skip-health-check',
            '--output',str(result),'--full-body','--junit-xml',str(tmp_path/'result.xml')],
            capture_output=True,text=True,encoding='utf-8',timeout=60)
        assert completed.returncode==0,completed.stdout+completed.stderr
        book=load_workbook(result,read_only=True)
        cells='\n'.join(str(v) for sheet in book for row in sheet.values for v in row)
        book.close()
        assert PASSWORD not in cells and TOKEN not in cells
        assert PASSWORD not in completed.stdout and TOKEN not in completed.stdout
        assert '[REDACTED]' in cells
        assert len(fixture.calls)==len(cases)+1
        if os.environ.get('OTG_LOGIN_EVIDENCE_DIR'):
            import shutil
            evidence=Path(os.environ['OTG_LOGIN_EVIDENCE_DIR'])
            evidence.mkdir(parents=True,exist_ok=True)
            shutil.copy2(result,evidence/'result.xlsx')
            shutil.copy2(tmp_path/'result.xml',evidence/'result.xml')
    finally:
        fixture.close()
