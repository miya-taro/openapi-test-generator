"""Compare the entire bounded scope; no writes, no inferred expectations."""
from copy import deepcopy
from decimal import Decimal

from src.influx_bulk import validate_bulk
from src.influx_mutation import fixture_timestamp
from src.expectation_rules import evaluate, equal
from db_backends import influx_response as influx
from db_backends.postgres_backend import DBResponseCheckUnverified


def snapshot(check, config):
    scope = check['scope']
    with influx._client(config) as client:
        table = influx._quote_ident(check['measurement'])
        tags = sorted(p['tagKey'] for p in client.query(f'SHOW TAG KEYS FROM {table}').get_points())
        fields = sorted(p['fieldKey'] for p in client.query(f'SHOW FIELD KEYS FROM {table}').get_points())
        if not fields:
            raise DBResponseCheckUnverified('measurementの定義がありません')
        if set(scope['tags']) - set(tags) or set(check['target']['tags']) - set(tags) or set(check['fields']) - set(fields):
            raise ValueError('存在しないタグまたはフィールドが指定されています')
        rows = influx._select(client, check['measurement'], [('time', '>=', scope['start']), ('time', '<=', scope['end']),
                              *((k, '=', v) for k, v in scope['tags'].items())])
    if len(rows) > influx.MAX_POINTS:
        raise DBResponseCheckUnverified('確認範囲が5000ポイントを超えています')
    result = {}
    for row in rows:
        key = (fixture_timestamp(row['time']), *(row.get(tag) for tag in tags))
        if key in result:
            raise ValueError('ポイントの識別子が重複しています')
        result[key] = row
    return result, tags, fields


def prepare(check, config, context):
    validate_bulk(check)
    before, tags, fields = snapshot(check, config)
    expected = deepcopy(before)
    target = check['target']
    count = 0
    for key, point in before.items():
        if fixture_timestamp(target['start']) <= key[0] <= fixture_timestamp(target['end']) and all(point.get(k) == v for k, v in target['tags'].items()):
            count += 1
            if check['action'] == 'delete':
                del expected[key]
            else:
                for field, expr in check['fields'].items():
                    value = evaluate(expr, {**context, 'point': point})
                    if not isinstance(value, (str, int, float, bool, Decimal)):
                        raise ValueError('期待フィールド値は数値・文字列・真偽値で指定してください')
                    expected[key][field] = value
    if count == 0 or equal(list(before.values()), list(expected.values())):
        raise DBResponseCheckUnverified('変更対象が0件、または実行前と期待値が同じため変更を判定できません')
    return {'definition': check, 'before_points': list(before.values()), 'expected_points': list(expected.values()),
            'target_count': count, 'guard_count': len(before) - count, 'tag_keys': tags, 'field_keys': fields,
            'verdict': '未確認'}


def verify(check, config, evidence):
    after, tags, fields = snapshot(check, config)
    rows = list(after.values())
    ok = tags == evidence['tag_keys'] and fields == evidence['field_keys'] and equal(evidence['expected_points'], rows, ordered=False)
    evidence.update(after_points=rows, before_count=len(evidence['before_points']), after_count=len(rows), verdict='OK' if ok else 'NG')
    return ok, '' if ok else '一括変更の値・件数・欠落・余分な変更が期待値と一致しません'
