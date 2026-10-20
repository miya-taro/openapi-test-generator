#!/usr/bin/env python3
"""Run or serve a disposable HTTP + PostgreSQL + InfluxDB 1.x API lab."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'runner')]

from docs.db_lab_service import DatabaseLab
from docs.db_lab_cases import specifications, scenarios, faulty_cases
from workflow.case_master import build_case_master, write_case_master


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')



def junit_matches(cases, junit):
    expected = {case['caseId']: case['status'] for case in cases}
    if len(expected) != len(cases) or len(junit) != len(cases):
        return False
    if {node.get('name') for node in junit} != set(expected):
        return False
    for node in junit:
        if node.find('skipped') is not None:
            return False
        failed = node.find('failure') is not None or node.find('error') is not None
        if failed != (expected[node.get('name')] == 'failed'):
            return False
    return True


def execute(output, label, definitions, spec, config_path, auth_path, url, expected='passed', invalid_token=False):
    folder = output / label
    folder.mkdir()
    write(folder / 'scenarios.json', {'scenarios': definitions})
    write(folder / 'openapi.json', spec)
    master = build_case_master(label, None, folder / 'scenarios.json', folder / 'openapi.json')
    write_case_master(master, folder / 'case-master.json')
    env = {k: v for k, v in os.environ.items() if not k.startswith('TEST_AUTH_')}
    if invalid_token:
        env.update(TEST_AUTH_HEADER_NAME='auth-key', TEST_AUTH_HEADER_VALUE='invalid-lab-token')
    env['NETRC'] = os.devnull
    command = [sys.executable, str(ROOT / 'runner/pytest_runner.py'), str(folder / 'case-master.json'),
               '--kind', 'db-scenario', '--base-url', url, '--config', str(config_path),
               '--skip-health-check', '--output', str(folder / 'result.xlsx'), '--junit-xml', str(folder / 'junit.xml')]
    if auth_path is not None:
        command.extend(['--auth-config', str(auth_path)])
    with (folder / 'run.log').open('w', encoding='utf-8') as log:
        process = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    result_path = folder / 'result.json'
    if not result_path.exists():
        raise RuntimeError(f'{label}: runner exit {process.returncode}; see {folder / "run.log"}')
    cases = json.loads(result_path.read_text(encoding='utf-8'))['cases']
    junit = list(ET.parse(folder / 'junit.xml').getroot().iter('testcase'))
    correct = (len(cases) == len(definitions) and junit_matches(cases, junit) and
               all(case['status'] == expected and str(case['actualStatus']) == str(definition['response_check']['expect']['status'])
                   for case, definition in zip(cases, definitions, strict=True)) and process.returncode == (0 if expected == 'passed' else 1))
    result = {'label': label, 'expected': expected, 'matched': correct, 'exitCode': process.returncode,
              'cases': [{**{k: row.get(k) for k in ('caseId', 'status', 'actualStatus', 'detail')},
                         'title': row.get('evidence', {}).get('name')} for row in cases],
              'evidence': str(result_path.relative_to(output))}
    print(label, dict(Counter(case['status'] for case in cases)), 'OK' if correct else 'MISMATCH', flush=True)
    return result


def run(config, output, *, serve=False, port=0, legacy=False):
    output.mkdir(parents=True, exist_ok=False)
    summary = {'startedAt': datetime.now(timezone.utc).isoformat(), 'engine': 'native-pytest', 'runs': []}
    summary['sourceCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    summary['sourceFiles'] = {}
    for name in ('db_lab_service.py', 'db_lab_cases.py', 'run_db_lab.py'):
        source = (ROOT / 'docs' / name).read_bytes()
        (output / name).write_bytes(source)
        summary['sourceFiles']['docs/' + name] = hashlib.sha256(source).hexdigest()
    lab = DatabaseLab(config, port)
    try:
        config_path, auth_path = output / 'db-config.json', output / 'auth.json'
        write(config_path, lab.config)
        write(auth_path, {'login_url': '/v1/auth/login', 'method': 'POST',
                         'body': {'username': 'fixture-user', 'password': 'fixture-password-only'},
                         'token_path': 'id', 'header_name': 'auth-key', 'header_format': '{token}'})
        spec = specifications()
        normal = scenarios(lab)
        write(output / 'openapi.json', spec)
        write(output / 'scenarios.json', {'scenarios': normal})
        write(output / 'connection.json', {'baseUrl': lab.url, 'recordsTable': lab.records, 'sitesTable': lab.sites,
                                          'influxDatabase': lab.config['influxdb']['database']})
        if serve:
            print(f'Lab listening: {lab.url}\nDefinitions: {output}\nCtrl+C stops and removes only this lab instance.', flush=True)
            while True:
                time.sleep(1)
        summary['runs'].append(execute(output, 'normal', normal, spec, config_path, auth_path, lab.url))
        # Re-run against fresh seed to check isolation and repeatability.
        lab.reset()
        summary['runs'].append(execute(output, 'repeat', normal, spec, config_path, auth_path, lab.url))
        summary['flowCleanupConfirmed'] = not lab.sql(f'SELECT id FROM {lab.records} WHERE id=70', fetch=True)
        guard = {'engine': 'postgres', 'table': lab.records, 'columns': ['id', 'name', 'amount', 'enabled', 'meta', 'note'], 'where': {}}
        denied = {'name': 'authentication rejected without DB change',
                  'request': {'operationId': 'labCreate', 'body': {'id': 80, 'name': 'denied', 'amount': 1, 'enabled': True}},
                  'response_check': {'expect': {'status': 401}}, 'db_unchanged': [guard]}
        for label, invalid in [('missing-auth', False), ('invalid-auth', True)]:
            summary['runs'].append(execute(output, label, [denied], spec, config_path, None, lab.url, invalid_token=invalid))
        wrong_login = {**denied, 'name': 'invalid password', 'request': {'operationId': 'labLogin',
                       'body': {'username': 'fixture-user', 'password': 'wrong'}}}
        summary['runs'].append(execute(output, 'invalid-login', [wrong_login], spec, config_path, None, lab.url))
        lab.fault = 'auth-write'
        summary['runs'].append(execute(output, 'fault-auth-write', [denied], spec, config_path, None, lab.url, 'failed'))
        for index, (fault, definition) in enumerate(faulty_cases(normal), 1):
            lab.reset()
            lab.fault = fault
            summary['runs'].append(execute(output, f'fault-{index:02d}-{fault}', [definition], spec,
                                           config_path, auth_path, lab.url, 'failed'))
            write(output / 'summary.json', summary)
        summary['fixtureErrors'] = lab.errors
        summary['httpRequests'] = len(lab.calls)
        summary['authenticatedRequests'] = sum(call['authenticated'] for call in lab.calls)
        if legacy:
            run_legacy(config, output, summary, auth_path)
    except KeyboardInterrupt:
        summary['interrupted'] = True
    finally:
        lab.close()
        summary['cleanupComplete'] = True
        summary['finishedAt'] = datetime.now(timezone.utc).isoformat()
        summary['counts'] = dict(Counter((row['expected'] if row['matched'] else 'mismatch')
                                         for row in summary['runs'] for _ in row['cases']))
        write(output / 'summary.json', summary)
    return summary


def run_legacy(config, output, summary, auth_path):
    from docs.authenticated_fixture import AuthenticatedFixture
    from docs.login_fixture_api import LoginFixture
    from docs.plan_fixture_api import PlanFixture
    from docs.plan_get_fixture_api import PlanGetFixture
    from docs.pwrco_fixture_api import PwrcoFixture
    from docs.plan_test_suites import post_suite, get_suite
    from docs.pwrco_suite import build_suite
    for name, cls, spec_file, fault in [
        ('plan-post', PlanFixture, 'examples/plan-post-openapi.json', 'numeric'),
        ('plan-get', PlanGetFixture, 'examples/plan-get/openapi.json', 'value'),
        ('pwrco', PwrcoFixture, 'examples/pwrco/openapi.json', 'rate'),
    ]:
        fixture, login, gateway = cls(config['postgres']), LoginFixture(), None
        try:
            spec = json.loads((ROOT / spec_file).read_text(encoding='utf-8'))
            gateway = AuthenticatedFixture(login.url, fixture.url, next(iter(spec['paths'])))
            suite = (post_suite(fixture.table, fixture.site_table) if name == 'plan-post' else
                     get_suite(fixture.definition()) if name == 'plan-get' else
                     build_suite('2039-01-01T00:00:00+09:00', fixture.table, fixture.site_table))
            summary['runs'].append(execute(output, name, suite['scenarios'], spec, output / 'db-config.json', auth_path, gateway.url))
            fixture.fault = fault
            if name == 'pwrco':
                suite = build_suite('2040-01-01T00:00:00+09:00', fixture.table, fixture.site_table)
            summary['runs'].append(execute(output, name + '-fault', suite['scenarios'][:1], spec,
                                           output / 'db-config.json', auth_path, gateway.url, 'failed'))
        finally:
            if gateway:
                gateway.close()
            login.close()
            fixture.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'examples/db-lab/config.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--serve', action='store_true', help='Keep service running for manual UI checks')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--legacy', action='store_true', help='Also qualify the existing plan POST/GET and pwrco APIs')
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('Use a new output directory; old evidence is never overwritten')
    result = run(json.loads(args.config.read_text(encoding='utf-8')), args.output_dir.resolve(),
                 serve=args.serve, port=args.port, legacy=args.legacy)
    if not args.serve:
        print(json.dumps(result['counts']), flush=True)
        raise SystemExit(0 if result['runs'] and all(row['matched'] for row in result['runs']) and
                         not result.get('fixtureErrors') and result.get('flowCleanupConfirmed') else 1)
