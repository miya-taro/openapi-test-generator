"""Explicit, serializable single-point mutation contract shared by UI and runner."""
import math
import re
from datetime import datetime

from src.db_scope import IDENTIFIER
from src.comparison_rules import comparable
from rfc3339_validator import validate_rfc3339


def fixture_timestamp(value):
    digits = re.search(r'\.(\d+)', value)
    if digits and digits[1][9:].strip('0'):
        raise ValueError('検証用ポイントの時刻はナノ秒までで指定してください')
    seconds, fraction = comparable(value, {'format': 'date-time'})
    fraction_ns = fraction * 10**9
    if fraction_ns != fraction_ns.to_integral_value():
        raise ValueError('検証用ポイントの時刻はナノ秒までで指定してください')
    timestamp = (seconds - datetime(1970, 1, 1).toordinal() * 86400) * 10**9 + int(fraction_ns)
    if not -(2**63 - 2) <= timestamp <= 2**63 - 2:
        raise ValueError('検証用ポイントの時刻がInfluxDBの範囲外です')
    return timestamp


def validate_mutation(value):
    if not isinstance(value, dict) or set(value) - {'measurement', 'time', 'tags', 'fields', 'action', 'preserve_unmapped', 'fixture'}:
        raise ValueError('InfluxDB変更確認の設定形式が不正です')
    if value.get('action') not in ('insert', 'update', 'delete'):
        raise ValueError('InfluxDB変更確認はinsert・update・deleteを指定してください')
    measurement = value.get('measurement')
    if not isinstance(measurement, str) or not IDENTIFIER.fullmatch(measurement):
        raise ValueError('有効なmeasurement名が必要です')
    when = value.get('time')
    if not isinstance(when, str) or not validate_rfc3339(when.upper()):
        raise ValueError('ポイント時刻はタイムゾーン付き日時を指定してください')
    tags = value.get('tags')
    if not isinstance(tags, dict) or not all(isinstance(k, str) and IDENTIFIER.fullmatch(k) and k != 'time'
                                           and isinstance(v, str) and v for k, v in tags.items()):
        raise ValueError('タグはタグ名と空でない文字列値のオブジェクトにしてください')
    fields = value.get('fields', {})
    if not isinstance(fields, dict) or not all(isinstance(k, str) and IDENTIFIER.fullmatch(k) and k != 'time'
                                             and k not in tags for k in fields):
        raise ValueError('期待フィールドはtime・タグと重複しない項目にしてください')
    for v in fields.values():
        if not isinstance(v, (str, int, float, bool)) or (isinstance(v, (int, float)) and not math.isfinite(v)):
            raise ValueError('期待フィールドには文字列・有限数値・booleanを指定してください')
    if value['action'] != 'delete' and not fields:
        raise ValueError('保存・更新で照合するフィールドを1件以上指定してください')
    if value['action'] == 'delete' and fields:
        raise ValueError('削除確認には期待フィールドを設定しません')
    if not isinstance(value.get('preserve_unmapped', False), bool):
        raise ValueError('未指定フィールドの維持設定は真偽値にしてください')
    if 'fixture' in value:
        fixture_timestamp(when)
        fixture = value['fixture']
        if not isinstance(fixture, dict) or set(fixture) != {'fields'} or not isinstance(fixture['fields'], dict):
            raise ValueError('検証用ポイントには初期フィールドを指定してください')
        seeds = fixture['fields']
        if value['action'] == 'insert' and seeds:
            raise ValueError('新規保存の試験では初期ポイントを投入しません')
        if value['action'] != 'insert' and not seeds:
            raise ValueError('更新・削除の試験には初期フィールドが必要です')
        for key, spec in seeds.items():
            if not isinstance(key, str) or not IDENTIFIER.fullmatch(key) or key == 'time' or key in tags:
                raise ValueError('初期フィールド名はtime・タグと重複しない名前にしてください')
            if not isinstance(spec, dict) or set(spec) != {'type', 'value'}:
                raise ValueError('初期フィールドにはtypeとvalueが必要です')
            kind, v = spec['type'], spec['value']
            valid = ((kind == 'string' and isinstance(v, str)) or
                     (kind == 'boolean' and isinstance(v, bool)) or
                     (kind == 'integer' and type(v) is int and -(2**63) <= v < 2**63) or
                     (kind == 'float' and type(v) in (int, float) and math.isfinite(v)))
            if not valid:
                raise ValueError('初期フィールドの型と値が一致しません（string/integer/float/boolean）')
    return value
