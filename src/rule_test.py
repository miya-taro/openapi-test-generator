"""Validation for explicit rule-test data and response projections."""
import math
import re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
PATH = re.compile(r'^(?:\$|[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*)$')


def identifier(value):
    return isinstance(value, str) and IDENT.fullmatch(value)


def validate_fixture(value):
    if not isinstance(value, dict) or set(value) - {'engine', 'table', 'scope', 'rows', 'field_types'}:
        raise ValueError('検証データにはengine・table・scope・rows・field_typesを指定してください')
    if value.get('engine') not in ('postgres', 'influxdb') or not identifier(value.get('table')):
        raise ValueError('検証データのDB種別とテーブル名を指定してください')
    scope = value.get('scope')
    if not isinstance(scope, dict) or not scope or not all(identifier(k) for k in scope):
        raise ValueError('検証データの専用範囲を1項目以上指定してください')
    if any(v is None or type(v) not in (str, int, float, bool) or (type(v) is float and not math.isfinite(v)) for v in scope.values()):
        raise ValueError('専用範囲にはnull以外の固定値を指定してください')
    rows = value.get('rows')
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('検証データは0〜100行で指定してください')
    for row in rows:
        if not isinstance(row, dict) or not all(identifier(k) for k in row):
            raise ValueError('検証データの列名が不正です')
        if any(k not in row or type(row[k]) is not type(v) or row[k] != v for k, v in scope.items()):
            raise ValueError('すべての検証行を専用範囲に一致させてください')
    if value['engine'] == 'influxdb':
        if any(not isinstance(v, str) or not v for v in scope.values()) or 'time' in scope:
            raise ValueError('InfluxDBの専用範囲には全タグを文字列で指定してください')
        from src.influx_mutation import validate_mutation, fixture_timestamp
        types = value.get('field_types', {})
        if not isinstance(types, dict):
            raise ValueError('InfluxDBのフィールド型を指定してください')
        seen = set()
        for row in rows:
            fields = {k: {'type': types.get(k), 'value': v} for k, v in row.items() if k not in scope and k != 'time'}
            if not fields:
                raise ValueError('InfluxDBの検証ポイントにはフィールドが必要です')
            check = {'measurement': value['table'], 'time': row.get('time'), 'tags': scope,
                     'action': 'delete', 'fields': {}, 'fixture': {'fields': fields}}
            validate_mutation(check)
            timestamp = fixture_timestamp(row['time'])
            if timestamp in seen:
                raise ValueError('検証ポイントの時刻が重複しています')
            seen.add(timestamp)
    return value


def validate_collections(collections):
    if not isinstance(collections, list):
        raise ValueError('配列の期待値はリストで指定してください')
    for rule in collections:
        if not isinstance(rule, dict) or set(rule) != {'path', 'fields', 'rows'}:
            raise ValueError('配列の照合にはpath・fields・rowsを指定してください')
        if not isinstance(rule['path'], str) or not PATH.fullmatch(rule['path']):
            raise ValueError('配列パスが不正です（入れ子配列には[]を使用）')
        fields = rule['fields']
        if not isinstance(fields, list) or not fields or not all(
                isinstance(p, str) and PATH.fullmatch(p) and '[]' not in p for p in fields) or len(set(fields)) != len(fields):
            raise ValueError('照合するレスポンス項目を重複なしで指定してください')
        if not isinstance(rule['rows'], list) or len(rule['rows']) > 100 or not all(
                isinstance(row, dict) and set(row) == set(fields) for row in rule['rows']):
            raise ValueError('期待する行は照合項目と一致する0〜100件の値を指定してください')
    return collections


def validate_rule(rule, fixture):
    if not isinstance(rule, dict) or rule.get('kind') not in ('boundary', 'combinations', 'priority', 'empty'):
        raise ValueError('試験ルールの種類が不正です')
    if not isinstance(rule.get('condition'), str) or not rule['condition'].strip():
        raise ValueError('試験条件を指定してください')
    if 'body_present' in rule and type(rule['body_present']) is not bool:
        raise ValueError('body_presentは真偽値で指定してください')
    if rule['kind'] in ('boundary', 'priority', 'empty') and fixture is None:
        raise ValueError('境界・優先順位・0件の試験には専用の検証データ設定が必要です')
    if rule['kind'] == 'empty' and fixture['rows']:
        raise ValueError('0件試験の検証範囲には行を投入できません')
    if rule['kind'] in ('boundary', 'priority') and len(fixture['rows']) < 2:
        raise ValueError('境界・優先順位の試験には比較する2行以上が必要です')
    return rule
