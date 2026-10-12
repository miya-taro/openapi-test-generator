"""Read-only before/after evidence for an explicit POST array-to-row contract."""
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

from config_loader import get_postgres_config
from src.insert_mapping import validate_insert
from db_backends import lookup_response
from db_backends.postgres_backend import DBResponseCheckUnverified, _quote_ident

MAX_ROWS = 5000
MAX_EXPECTED = 1000
MISSING = object()


def contexts(body, path):
    states = [(body, {})]
    parts = path.split('.')
    for index, part in enumerate(parts):
        prefix = '.'.join(parts[:index + 1])
        expanded = []
        for value, indices in states:
            name = part.removesuffix('[]')
            if not isinstance(value, dict) or name not in value:
                raise ValueError(f'保存対象の配列がありません: {prefix}')
            child = value[name]
            if part.endswith('[]'):
                if not isinstance(child, list):
                    raise ValueError(f'{prefix}は配列で指定してください')
                for i, item in enumerate(child):
                    expanded.append((item, {**indices, prefix: i}))
            else:
                expanded.append((child, indices))
            if len(expanded) > MAX_EXPECTED:
                raise DBResponseCheckUnverified(f'保存行の展開が{MAX_EXPECTED}件を超えます')
        states = expanded
    return [indices for _, indices in states]


def value_at(body, path, indices):
    value = body
    for i, part in enumerate(path.split('.')):
        name = part.removesuffix('[]')
        if not isinstance(value, dict) or name not in value:
            return MISSING
        value = value[name]
        if part.endswith('[]'):
            index = indices.get('.'.join(path.split('.')[:i + 1]))
            if not isinstance(value, list) or index is None or index >= len(value):
                return MISSING
            value = value[index]
    return value


def combined_datetime(day, clock, zone):
    if not isinstance(day, str) or not isinstance(clock, str):
        raise ValueError('日時の組み立てには日付と時刻の文字列が必要です')
    # The configured zone determines the calendar date for an offset datetime.
    if 'T' in day:
        parsed = datetime.fromisoformat(day.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('計画日時にはタイムゾーンが必要です')
        day_value = parsed.astimezone(ZoneInfo(zone)).date()
    else:
        day_value = date.fromisoformat(day)
    clock_value = time.fromisoformat(clock)
    if clock_value.tzinfo is not None:
        raise ValueError('時刻はオフセットなしで指定し、タイムゾーン欄で指定してください')
    local = datetime.combine(day_value, clock_value)
    tz = ZoneInfo(zone)
    possibilities = {local.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
                     if local.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == local}
    if len(possibilities) != 1:
        raise ValueError('夏時間の切替で存在しない、または曖昧な時刻です')
    return possibilities.pop()


def expected_rows(check, body, config, records):
    validate_insert(check)
    rows, cache = [], {}
    for indices in contexts(body, check['rows_path']):
        row = {}
        for column, rule in check['columns'].items():
            kind = rule['kind']
            if kind == 'runtime':
                continue
            if kind == 'fixed':
                value = rule['value']
            elif kind == 'datetime':
                value = combined_datetime(value_at(body, rule['date'], indices), value_at(body, rule['time'], indices), rule['timezone'])
            elif kind == 'lookup':
                preferred = value_at(body, rule['preferred_path'], indices) if rule.get('preferred_path') else MISSING
                if preferred is not MISSING:
                    value = preferred
                else:
                    key = value_at(body, rule['path'], indices)
                    if key is MISSING:
                        raise ValueError(f'{column}: 優先項目・参照項目のどちらもありません')
                    identity = json.dumps([rule['lookup'], key], sort_keys=True)
                    if identity not in cache:
                        found = lookup_response._read_values(config, rule['lookup'], key)
                        if len(found) != 1:
                            raise DBResponseCheckUnverified(f'{column}: 参照結果が{len(found)}件です。1件が必要です')
                        cache[identity] = lookup_response._convert(found[0], rule['lookup'].get('value_type', 'as_is'))
                        records.append({'parameter': rule['path'], 'definition': rule['lookup'], 'input_value': key,
                                        'target_column': column, 'values': [cache[identity]], 'verdict': '取得済み'})
                    value = cache[identity]
            else:
                value = value_at(body, rule['path'], indices)
                if value is MISSING and rule.get('missing') == 'null':
                    value = None
            if value is MISSING:
                raise ValueError(f'{column}: 対応するリクエスト項目がありません')
            row[column] = value
        rows.append(row)
    if not rows:
        raise DBResponseCheckUnverified('保存対象が0行です。空配列の期待動作は別ケースで指定してください')
    return rows


def snapshot(check, config):
    conn = psycopg2.connect(**get_postgres_config(config))
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid '
                        'AND a.attnum=ANY(i.indkey) WHERE i.indrelid=%s::regclass AND i.indisprimary', (_quote_ident(check['table']),))
            keys = {r['attname'] for r in cur.fetchall()}
            if keys != set(check['primary_key']):
                raise ValueError('設定した複合主キーがDB定義と一致しません')
            cur.execute(f'SELECT * FROM {_quote_ident(check["table"])} LIMIT %s', (MAX_ROWS + 1,))
            rows = [dict(r) for r in cur.fetchall()]
            columns = {desc.name for desc in cur.description}
            if not set(check['columns']) <= columns:
                raise ValueError('対応付けたDB列が存在しません')
            if len(rows) > MAX_ROWS:
                raise DBResponseCheckUnverified(f'保存先が{MAX_ROWS}行を超えます。専用の検証DBで実行してください')
            return rows
    finally:
        conn.rollback()
        conn.close()


def equal(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, datetime) or isinstance(expected, datetime):
        try:
            a = actual if isinstance(actual, datetime) else datetime.fromisoformat(actual.replace('Z', '+00:00'))
            b = expected if isinstance(expected, datetime) else datetime.fromisoformat(expected.replace('Z', '+00:00'))
            return a.tzinfo is not None and b.tzinfo is not None and a == b
        except (ValueError, TypeError, AttributeError):
            return False
    if isinstance(actual, (int, float, Decimal)) and isinstance(expected, (int, float, Decimal)):
        return Decimal(str(actual)) == Decimal(str(expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(equal(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(equal(a, b) for a, b in zip(actual, expected, strict=True))
    return type(actual) is type(expected) and actual == expected


def compare(check, before, after, expected, started, ended, evidence):
    keys = check['primary_key']
    def index(rows):
        return {tuple(r[k] for k in keys): r for r in rows}
    old, new = index(before), index(after)
    added = [r for key, r in new.items() if key not in old]
    changed = [r for key, r in old.items() if key not in new or not equal(new[key], r)]
    pending = list(added)
    missing = []
    def matches(actual, wanted):
        if not all(equal(actual.get(k), v) for k, v in wanted.items()):
            return False
        for column, rule in check['columns'].items():
            if rule['kind'] != 'runtime':
                continue
            stamp = actual.get(column)
            if not isinstance(stamp, datetime):
                try:
                    stamp = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                except (AttributeError, TypeError, ValueError):
                    return False
            tolerance = timedelta(seconds=rule['tolerance_seconds'])
            if stamp.tzinfo is None or not started - tolerance <= stamp <= ended + tolerance:
                return False
        return True
    for row in expected:
        position = next((i for i, actual in enumerate(pending) if matches(actual, row)), None)
        if position is None:
            missing.append(row)
        else:
            pending.pop(position)
    ok = not (changed or missing or pending)
    evidence.update(before_rows=before, after_rows=after, added_rows=added, expected_rows=expected,
                    expected_count=len(expected), actual_count=len(added), missing_rows=missing,
                    extra_or_mismatched_rows=pending, changed_or_deleted_rows=changed,
                    started=started, ended=ended, verdict='OK' if ok else 'NG')
    return ok, f'複数行保存: 期待{len(expected)}行 / 追加{len(added)}行、未一致{len(missing)}行、余分・値違い{len(pending)}行、既存変更・削除{len(changed)}行'
