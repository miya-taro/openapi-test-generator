"""Explicit POST array-to-row mapping validation, shared by scenario entrypoints."""
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from src.db_lookup import IDENT, validate_lookup

PATH = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$')


def valid_path(path):
    return isinstance(path, str) and bool(PATH.fullmatch(path)) and len(path.split('.')) <= 12


def validate_insert(check):
    if not isinstance(check, dict) or set(check) - {'table', 'primary_key', 'rows_path', 'columns'}:
        raise ValueError('複数行保存の設定項目が不正です')
    if not isinstance(check.get('table'), str) or not IDENT.fullmatch(check['table']):
        raise ValueError('保存先テーブル名を指定してください')
    keys = check.get('primary_key')
    if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not IDENT.fullmatch(k) for k in keys) or len(set(keys)) != len(keys):
        raise ValueError('複合主キーを重複のないDB列名で指定してください')
    path = check.get('rows_path')
    if not valid_path(path) or not path.endswith('[]'):
        raise ValueError('保存行に対応する配列パスを指定してください（例: plans[].controls[]）')
    columns = check.get('columns')
    if not isinstance(columns, dict) or not columns:
        raise ValueError('保存列の対応付けが必要です')
    if not set(keys) <= columns.keys():
        raise ValueError('全主キー列の期待値・実行時刻のルールを指定してください')
    arrays = {'.'.join(path.split('.')[:i + 1]) for i, part in enumerate(path.split('.')) if part.endswith('[]')}
    def source(p):
        if not valid_path(p):
            raise ValueError('リクエストの項目パスが不正です')
        if any('.'.join(p.split('.')[:i + 1]) not in arrays for i, part in enumerate(p.split('.')) if part.endswith('[]')):
            raise ValueError('対応する保存行とは別の配列を参照できません')
    allowed = {
        'request': {'kind', 'path', 'missing'}, 'fixed': {'kind', 'value'},
        'datetime': {'kind', 'date', 'time', 'timezone'}, 'runtime': {'kind', 'tolerance_seconds'},
        'lookup': {'kind', 'path', 'preferred_path', 'lookup'},
    }
    for column, rule in columns.items():
        if not isinstance(column, str) or not IDENT.fullmatch(column) or not isinstance(rule, dict):
            raise ValueError('DB列名・対応ルールが不正です')
        kind = rule.get('kind')
        if kind not in allowed or set(rule) - allowed[kind]:
            raise ValueError(f'{column}: 対応ルールが不正です')
        if kind in {'request', 'lookup'}:
            source(rule.get('path'))
        if kind == 'request' and rule.get('missing', 'error') not in {'error', 'null'}:
            raise ValueError('項目省略時はエラーまたは明示したnullを指定してください')
        if kind == 'fixed' and 'value' not in rule:
            raise ValueError('固定値がありません')
        if kind == 'runtime':
            tolerance = rule.get('tolerance_seconds')
            if type(tolerance) not in (float, int) or not math.isfinite(tolerance) or not 0 <= tolerance <= 3600:
                raise ValueError('実行時刻の許容秒数は0〜3600を明示してください')
        if kind == 'datetime':
            source(rule.get('date'))
            source(rule.get('time'))
            try:
                ZoneInfo(rule.get('timezone', ''))
            except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
                raise ValueError('日時を組み立てるタイムゾーンを指定してください') from exc
        if kind == 'lookup':
            if rule.get('preferred_path'):
                source(rule['preferred_path'])
            lookup = rule.get('lookup')
            validate_lookup(lookup, '=', False)
            if lookup['cardinality'] != 'one' or lookup['on_empty'] != 'unverified':
                raise ValueError('保存キーの参照は1件を要求し、0件なら未確認で停止します')
    return check
