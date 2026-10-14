"""Reusable cases for the documented plan examples; no inferred business rules.

Run from the repository root: python -m docs.plan_test_suites --output-dir PATH
The output can be loaded as OpenAPI / DB scenarios in the existing UI.
"""
import argparse
import copy
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUANTITIES = ('buy', 'sell', 'charge', 'discharge', 'soc', 'gen', 'suppression')
POST_COLUMNS = ['datetime', 'created', 'site_id', 'use_id', 'manual', 'fixed',
                'force', 'cpbs_type', 'profit', *QUANTITIES, 'correct_point']


def post_mapping(table='h_plan', site_table='t_site'):
    columns = {
        'site_id': {'kind': 'lookup', 'path': 'location_id', 'preferred_path': 'site_id',
                    'lookup': {'engine': 'postgres', 'table': site_table,
                               'match_column': 'location_id', 'value_column': 'site_id',
                               'cardinality': 'one', 'value_type': 'integer', 'on_empty': 'unverified'}},
        'use_id': {'kind': 'request', 'path': 'type'},
        'datetime': {'kind': 'datetime', 'date': 'plans[].date',
                     'time': 'plans[].controls[].time', 'timezone': 'Asia/Tokyo'},
        'created': {'kind': 'runtime', 'tolerance_seconds': 5},
        'manual': {'kind': 'fixed', 'value': False},
        'fixed': {'kind': 'fixed', 'value': False},
        'cpbs_type': {'kind': 'fixed', 'value': 0},
        'force': {'kind': 'request', 'path': 'force'},
        'profit': {'kind': 'request', 'path': 'plans[].profit'},
    }
    for name in (*QUANTITIES, 'correct_point'):
        columns[name] = {'kind': 'request', 'path': f'plans[].controls[].{name}'}
    return {'table': table, 'primary_key': ['datetime', 'created', 'site_id', 'use_id'],
            'rows_path': 'plans[].controls[]', 'columns': columns}


def post_body():
    body = json.loads((ROOT / 'examples/plan-post-request.json').read_text())
    # Distinct values make wrong parent/child associations observable.
    for day_index, plan in enumerate(body['plans']):
        plan['profit'] = 1000 + day_index
        for control_index, control in enumerate(plan['controls']):
            for field_index, field in enumerate(QUANTITIES):
                control[field] = day_index * 100 + control_index * 10 + field_index + .125
                control['correct_point']['start'][field] = control[field] + .25
    return body


def post_contract(table='h_plan', site_table='t_site'):
    api = json.loads((ROOT / 'examples/plan-post-openapi.json').read_text())
    operation = api['paths']['/v1/plan/set']['post']
    operation['requestBody']['content']['application/json']['schema']['example'] = post_body()
    operation['x-otg-error-db-unchanged'] = [
        {'table': table, 'columns': POST_COLUMNS, 'where': {}},
        {'table': site_table, 'columns': ['site_id', 'location_id'], 'where': {}},
    ]
    return api


def post_suite(table='h_plan', site_table='t_site'):
    cases = []
    for site, kind, correct, force in itertools.product(
            ('site', 'location', 'both-site-wins'), ('1-1', '2-1'), (False, True), (False, True)):
        body = post_body()
        if site == 'site':
            del body['location_id']
        elif site == 'location':
            del body['site_id']
            body['location_id'] = 'LOC001'
        body.update(type=kind, correct=correct, force=force)
        cases.append({'name': f'計画POST {site} / type={kind} / correct={correct} / force={force}',
                      'request': {'operationId': 'setPlan', 'body': body},
                      'response_check': {'expect': {'status': 200, 'empty_body': True}},
                      'db_insert_check': post_mapping(table, site_table)})
    single = copy.deepcopy(cases[0])
    single['name'] = '計画POST 1日・control 1件'
    single['request']['body']['plans'] = [single['request']['body']['plans'][0]]
    single['request']['body']['plans'][0]['controls'] = [single['request']['body']['plans'][0]['controls'][0]]
    cases.append(single)
    # These errors occur after at least one valid control/plan, exposing partial commits.
    for name, path in [
        ('2件目controlのtime欠落', ('plans', 0, 'controls', 1, 'time')),
        ('2件目planのprofit欠落', ('plans', 1, 'profit')),
        ('2件目planのcontrols空配列', ('plans', 1, 'controls')),
    ]:
        body = post_body()
        target = body
        for key in path[:-1]:
            target = target[key]
        if path[-1] == 'controls':
            target[path[-1]] = []
        else:
            del target[path[-1]]
        cases.append({'name': '計画POST 400・部分保存なし / ' + name,
                      'request': {'operationId': 'setPlan', 'body': body},
                      'response_check': {'expect': {'status': 400, 'empty_body': True}},
                      'db_unchanged': post_contract(table, site_table)['paths']['/v1/plan/set']['post']['x-otg-error-db-unchanged']})
    return {'scenarios': cases}


def get_suite(definition=None):
    raw = copy.deepcopy(definition) if definition is not None else json.loads(
        (ROOT / 'examples/plan-get/scenario.json').read_text())['scenarios'][0]
    cases = []
    for site, correct, kind in itertools.product(
            ('site', 'location', 'both-site-wins'), (None, False, True), (None, '1-1', '2-1')):
        case = copy.deepcopy(raw)
        body = case['request']['body']
        if site == 'site':
            body.pop('location_id', None)
        elif site == 'location':
            body.pop('site_id', None)
            body['location_id'] = 'HOME'
        for key, value in [('correct', correct), ('type', kind)]:
            body.pop(key, None)
            if value is not None:
                body[key] = value
        case['name'] = f'計画GET {site} / correct={correct if correct is not None else "省略"} / type={kind or "省略"}'
        cases.append(case)
    for name, start, end in [
        ('開始を含む・終了を含まない', '2026-10-12T00:00:00+09:00', '2026-10-12T00:30:00+09:00'),
        ('開始の直前を除外', '2026-10-12T00:00:00.000001+09:00', '2026-10-12T01:00:00+09:00'),
        ('終了の直前を含む', '2026-10-12T00:00:00+09:00', '2026-10-12T00:30:00.000001+09:00'),
        ('日付をまたぐ', '2026-10-12T00:30:00+09:00', '2026-10-13T00:30:00+09:00'),
        ('同じ期間をUTCで指定', '2026-10-11T15:00:00Z', '2026-10-13T15:00:00Z'),
    ]:
        case = copy.deepcopy(raw)
        case['name'] = '計画GET 境界 / ' + name
        case['request']['body'].update(start=start, end=end)
        cases.append(case)
    return {'scenarios': cases}


def empty_get_case(body, *, expected_status, expected_body):
    """Explicit expectation required: empty results do not imply 200 or 400."""
    if type(expected_status) is not int or not 100 <= expected_status <= 599:
        raise ValueError('0件時の期待statusを指定してください')
    if not isinstance(expected_body, dict):
        raise ValueError('0件時の期待レスポンスを指定してください')
    return {'name': f'計画GET 0件 / 明示した期待status={expected_status}',
            'request': {'operationId': 'getPlanControl', 'body': copy.deepcopy(body)},
            'response_check': {'expect': {'status': expected_status, 'values': [
                {'path': key, 'source': 'fixed', 'value': value} for key, value in expected_body.items()
            ]}}}


def write_examples(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in [('plan-post-openapi.json', post_contract()),
                       ('plan-post-scenarios.json', post_suite()),
                       ('plan-get-scenarios.json', get_suite())]:
        # One case per line keeps large request bodies out of repetitive diffs.
        if 'scenarios' in data:
            text = '{"scenarios": [\n' + ',\n'.join(json.dumps(case, ensure_ascii=False) for case in data['scenarios']) + '\n]}\n'
        else:
            text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        (directory / name).write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    write_examples(parser.parse_args().output_dir)
