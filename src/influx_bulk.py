"""Explicit bounded InfluxDB 1.x bulk change contract."""
from rfc3339_validator import validate_rfc3339
from src.influx_mutation import fixture_timestamp
from src.expectation_rules import validate_expr, IDENT


def validate_bulk(check):
    if not isinstance(check, dict) or set(check) != {'measurement', 'action', 'scope', 'target', 'fields'}:
        raise ValueError('一括照合にはmeasurement・処理・確認範囲・変更対象・期待フィールドを指定してください')
    if not isinstance(check['measurement'], str) or not IDENT.fullmatch(check['measurement']) or check['action'] not in {'update', 'delete'}:
        raise ValueError('一括照合は更新または削除を指定してください')
    for label in ('scope', 'target'):
        rule = check[label]
        if not isinstance(rule, dict) or set(rule) != {'start', 'end', 'tags'}:
            raise ValueError('範囲は開始・終了時刻とタグ条件を指定してください')
        if any(not isinstance(rule[k], str) or not validate_rfc3339(rule[k].upper()) for k in ('start', 'end')):
            raise ValueError('範囲の時刻はタイムゾーン付き日時で指定してください')
        if fixture_timestamp(rule['start']) > fixture_timestamp(rule['end']):
            raise ValueError('開始時刻が終了時刻より後です')
        if not isinstance(rule['tags'], dict) or any(not IDENT.fullmatch(k) or not isinstance(v, str) or not v for k, v in rule['tags'].items()):
            raise ValueError('タグ条件はタグ名と空でない文字列にしてください')
    outer, inner = check['scope'], check['target']
    if not (fixture_timestamp(outer['start']) <= fixture_timestamp(inner['start']) <= fixture_timestamp(inner['end']) <= fixture_timestamp(outer['end'])) or any(inner['tags'].get(k) != v for k, v in outer['tags'].items()):
        raise ValueError('変更対象は確認範囲に含まれる必要があります')
    if not isinstance(check['fields'], dict) or (check['action'] == 'delete' and check['fields']) or (check['action'] == 'update' and not check['fields']):
        raise ValueError('更新には期待フィールドが必要です。削除には指定しません')
    for key, expr in check['fields'].items():
        if not IDENT.fullmatch(key) or key == 'time':
            raise ValueError('変更するフィールド名を確認してください')
        validate_expr(expr, roots=('point', 'body', 'query', 'path'))
    return check
