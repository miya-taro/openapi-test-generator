"""Explicit API dependencies and bounded read polling; never retry a mutation."""
from __future__ import annotations

import copy
from dataclasses import fields, is_dataclass, replace
import math
import re
import time

_REFERENCE = re.compile(r'^\{\{steps\.([A-Za-z][A-Za-z0-9_]*)(?:\.([\w.]+))?\}\}$')
_NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,39}$')


def lookup(value, path):
    for part in path.split('.') if path else []:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError(f'レスポンス項目 {path} がありません')
    return value


def resolve(value, results):
    if isinstance(value, str) and '{{steps.' in value:
        match = _REFERENCE.fullmatch(value)
        if not match or match[1] not in results:
            raise ValueError('引き継ぐAPIの実行結果がありません、または参照形式が不正です')
        return copy.deepcopy(lookup(results[match[1]], match[2]))
    if is_dataclass(value):
        return replace(value, **{f.name: resolve(getattr(value, f.name), results) for f in fields(value)})
    if isinstance(value, dict):
        return {k: resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results) for v in value]
    return value


def validate_poll(poll):
    if poll is None:
        return
    if not isinstance(poll, dict) or set(poll) - {'path', 'equals', 'timeout', 'interval'}:
        raise ValueError('完了待ちの設定が不正です')
    if not isinstance(poll.get('path'), str) or not poll['path'] or 'equals' not in poll:
        raise ValueError('完了待ちにはレスポンス項目と期待値が必要です')
    for key, lower, upper in [('timeout', 0.1, 300), ('interval', 0.05, 60)]:
        value = poll.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f'完了待ちの{key}は{lower}〜{upper}秒です')
    if poll['interval'] > poll['timeout']:
        raise ValueError('確認間隔は期限以下にしてください')


def validate_flow(flow):
    if flow is None:
        return
    if not isinstance(flow, dict) or set(flow) - {'before', 'cleanup'}:
        raise ValueError('API手順の設定が不正です')
    names = {'result'}
    for phase in ('before', 'cleanup'):
        steps = flow.get(phase, [])
        if not isinstance(steps, list) or len(steps) > 20:
            raise ValueError('API手順は前処理・後片付けそれぞれ20件以内です')
        for step in steps:
            if not isinstance(step, dict) or set(step) - {'name', 'request', 'expect_status', 'expect_body', 'poll'}:
                raise ValueError('API手順に未対応の設定があります')
            name = step.get('name')
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
                raise ValueError('手順名は重複しない英数字・アンダースコアで指定してください（resultは予約名）')
            names.add(name)
            req = step.get('request')
            if not isinstance(req, dict) or not req.get('operationId') or set(req) - {'operationId', 'body', 'path_params', 'query_params'}:
                raise ValueError('手順のAPI操作・送信設定が不正です')
            if any(not isinstance(req.get(key, {}), dict) for key in ('body', 'path_params', 'query_params')):
                raise ValueError('送信するbody/path/queryはオブジェクトにしてください')
            if type(step.get('expect_status')) is not int or not 100 <= step['expect_status'] <= 599:
                raise ValueError('各手順に期待HTTPステータスが必要です')
            if not isinstance(step.get('expect_body', {}), dict):
                raise ValueError('期待レスポンスは項目と値で指定してください')
            validate_poll(step.get('poll'))


def validate_operations(scenario, api):
    from db_scenario_runner import _resolve_operation
    def references(value, available):
        if isinstance(value, str) and '{{steps.' in value:
            match = _REFERENCE.fullmatch(value)
            if not match or match[1] not in available:
                raise ValueError('参照先のAPI手順は使用箇所より前に定義してください')
        elif isinstance(value, dict):
            for item in value.values():
                references(item, available)
        elif isinstance(value, list):
            for item in value:
                references(item, available)
    available = set()
    flow = scenario.api_flow or {}
    for step in flow.get('before', []):
        references(step, available)
        available.add(step['name'])
    main = scenario.case_definition()
    main.pop('apiFlow', None)
    references(main, available)
    available.add('result')
    for step in flow.get('cleanup', []):
        references(step, available)
        available.add(step['name'])
    for step in [*(scenario.api_flow or {}).get('before', []),
                 {'request': {'operationId': scenario.request.operation_id}, 'poll': scenario.poll},
                 *(scenario.api_flow or {}).get('cleanup', [])]:
        _, method = _resolve_operation(api, step['request']['operationId'])
        if step.get('poll') and method != 'GET':
            raise ValueError('完了待ちはGET APIで設定してください。作成・更新APIは繰り返しません')


def call_with_poll(call, args, kwargs, poll, expected_status, attempts, response_validator=None):
    """One send by default. A poll repeats only a validated GET and stops on HTTP errors."""
    deadline = time.monotonic() + poll['timeout'] if poll else None
    while True:
        remaining = deadline - time.monotonic() if deadline else None
        if remaining is not None:
            kwargs = {**kwargs, 'timeout': max(0.001, remaining)}
        result = call(*args, **kwargs)
        status, body, error = result
        attempts.append({'attempt': len(attempts) + 1, 'status': status,
                         'body': body, 'request': getattr(result, 'request_evidence', {})})
        if error:
            return result, 'APIとの通信に失敗しました'
        if not poll:
            return result, None
        if time.monotonic() > deadline:
            return result, '期限内に完了条件を満たしませんでした'
        if response_validator:
            verdict, detail, _ = response_validator(result)
            if verdict != 'OK':
                return result, detail
        if status != expected_status:
            return result, f'完了待ちのHTTPステータス不一致: 期待={expected_status} 実測={status}'
        try:
            actual = lookup(body, poll['path'])
        except ValueError as exc:
            return result, str(exc)
        if type(actual) is type(poll['equals']) and actual == poll['equals']:
            return result, None
        if len(attempts) >= 1000 or time.monotonic() >= deadline:
            return result, '期限内に完了条件を満たしませんでした'
        time.sleep(min(poll['interval'], max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            return result, '期限内に完了条件を満たしませんでした'


def execute_step(step, api, base_url, session, cookies, auth, results, records, phase='before'):
    from db_scenario_runner import _call_api, _resolve_operation, _verify_response_contract
    from db_scenario import ResponseCheck, DBScenario, ScenarioRequest
    from response_check import check
    record = {'name': step['name'], 'phase': phase, 'operationId': step['request']['operationId'],
              'expectedStatus': step['expect_status'], 'expectedBody': step.get('expect_body', {}),
              'verdict': 'NG', 'attempts': [], 'poll': step.get('poll')}
    records.append(record)
    step = resolve(step, results)
    req = step['request']
    path, method = _resolve_operation(api, req['operationId'])
    args = (base_url, path, method, req.get('path_params', {}), req.get('body', {}), session, cookies)
    scenario = DBScenario(step['name'], ScenarioRequest(req['operationId']),
                          response_check=ResponseCheck(expect_status=step['expect_status']))
    response, error = call_with_poll(_call_api, args, {'auth_header': auth,
        'query_params': req.get('query_params', {}), 'send_empty_body': 'body' in req},
        step.get('poll'), step['expect_status'], record['attempts'],
        lambda response: _verify_response_contract(scenario, api, path, method, response))
    status, body, _ = response
    # Keep returned IDs for cleanup even when an assertion fails.
    results[step['name']] = body
    record.update(actualStatus=status, actualBody=body)
    ok, detail = check(ResponseCheck(expect_status=step['expect_status'], expect_body=step.get('expect_body', {})), status, body)
    verdict, contract_detail, _ = _verify_response_contract(scenario, api, path, method, response)
    if verdict != 'OK':
        error = error or contract_detail
    if error or not ok:
        record['detail'] = error or detail
        raise ValueError(f"手順 {step['name']}: {error or detail}")
    record.update(verdict='OK', detail='')


def run_flow(run_main, scenario, api, base_url, db_config, previous, session, cookies, auth, evidence):
    validate_operations(scenario, api)
    results, cleanup_errors = {}, []
    evidence = evidence if evidence is not None else {}
    records = evidence.setdefault('api_steps', [])
    outcome = (False, '前処理未完了', '未実行', previous, [])
    flow = scenario.api_flow or {}
    try:
        for step in flow.get('before', []):
            execute_step(step, api, base_url, session, cookies, auth, results, records)
        current = resolve(replace(scenario, api_flow=None), results)
        outcome = run_main(current, api, base_url, db_config, previous, session, cookies, auth, evidence)
        if evidence.get('response') or evidence.get('poll_attempts'):
            results['result'] = outcome[3]
    except ValueError as exc:
        outcome = (False, str(exc), 'ERR', previous, [])
        evidence['main_status'] = '未実行'
        completed = {row['name'] for row in records}
        for pending in flow.get('before', []):
            if pending['name'] not in completed:
                records.append({'name': pending['name'], 'operationId': pending['request']['operationId'],
                                'verdict': '未実行', 'detail': '前の手順が失敗したため送信していません', 'attempts': []})
    except Exception:
        outcome = (False, 'API手順の実行中にエラーが発生しました。設定・接続・実行記録を確認してください', 'ERR', previous, [])
    finally:
        for step in flow.get('cleanup', []):
            try:
                execute_step(step, api, base_url, session, cookies, auth, results, records, phase='cleanup')
            except Exception:
                cleanup_errors.append(f"後片付け手順 {step['name']} が完了しませんでした。実行記録を確認してください")
    ok, detail, status, body, errors = outcome
    return ok and not cleanup_errors, detail, status, body, [*errors, *cleanup_errors]
