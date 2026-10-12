"""Explicit PostgreSQL query and nested response mapping contract."""
import re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
PATH = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$')


def validate_sql_response(check):
    if not isinstance(check, dict) or set(check) - {'sql', 'parameters', 'fields', 'arrays'}:
        raise ValueError('SQL照合の定義が不正です')
    sql = check.get('sql', '')
    if not isinstance(sql, str) or not re.match(r'^\s*(SELECT|WITH)\b', sql, re.I) or ';' in sql.rstrip().removesuffix(';'):
        raise ValueError('期待値SQLはSELECTまたはWITHの1文で指定してください')
    parameters = check.get('parameters', {})
    if not isinstance(parameters, dict):
        raise ValueError('SQLパラメータの対応が不正です')
    for name, rule in parameters.items():
        if not isinstance(name, str) or not IDENT.fullmatch(name) or not isinstance(rule, dict) or set(rule) - {'source', 'path', 'missing'}:
            raise ValueError('SQLパラメータ名・定義が不正です')
        if rule.get('source') not in ('body', 'query', 'path') or not isinstance(rule.get('path'), str) or not PATH.fullmatch(rule['path']) or '[]' in rule['path']:
            raise ValueError('SQLパラメータはbody/query/pathの項目を指定してください')
        if rule.get('missing', 'error') not in ('error', 'null'):
            raise ValueError('SQLパラメータ省略時は停止またはNULLです')
    fields, arrays = check.get('fields'), check.get('arrays', [])
    if not isinstance(fields, dict) or not fields or not isinstance(arrays, list):
        raise ValueError('レスポンス項目とSQL結果列の対応が必要です')
    array_paths = set()
    for array in arrays:
        if not isinstance(array, dict) or set(array) - {'path', 'group_by', 'ordered'}:
            raise ValueError('配列設定が不正です')
        path = array.get('path', '')
        if not isinstance(path, str) or not PATH.fullmatch(path) or not path.endswith('[]') or path in array_paths:
            raise ValueError('配列パスが不正、または重複しています')
        keys = array.get('group_by', [])
        if not isinstance(keys, list) or any(not isinstance(k, str) or not IDENT.fullmatch(k) for k in keys) or len(set(keys)) != len(keys):
            raise ValueError('グループ列が不正です')
        if not isinstance(array.get('ordered', False), bool):
            raise ValueError('順序確認は真偽値です')
        array_paths.add(path)
    for path, column in fields.items():
        if not isinstance(path, str) or not PATH.fullmatch(path) or path.endswith('[]') or not isinstance(column, str) or not IDENT.fullmatch(column):
            raise ValueError('レスポンスパス・SQL列名が不正です')
        if len(path.split('.')) > 12:
            raise ValueError('レスポンス階層は12段までです')
        parts = path.split('.')
        for i, part in enumerate(parts):
            if part.endswith('[]') and '.'.join(parts[:i+1]) not in array_paths:
                raise ValueError('対応する全配列のグループ設定が必要です')
        if any(other.startswith(path + '.') for other in fields):
            raise ValueError('オブジェクト全体とその中身は同時に対応付けできません')
    for path in array_paths:
        if not any(field.startswith(path + '.') for field in fields):
            raise ValueError('配列内のレスポンス項目を対応付けてください')
        parent = path.split('.')[:-1]
        if any(part.endswith('[]') and '.'.join(parent[:i+1]) not in array_paths for i, part in enumerate(parent)):
            raise ValueError('親配列の設定が必要です')
    # Object and array cannot occupy the same JSON property.
    nodes = {}
    for path in [*fields, *array_paths]:
        for i, part in enumerate(path.split('.')):
            key = '.'.join(p.removesuffix('[]') for p in path.split('.')[:i+1])
            kind = part.endswith('[]')
            if key in nodes and nodes[key] != kind:
                raise ValueError('同じ項目を配列とオブジェクトにはできません')
            nodes[key] = kind
