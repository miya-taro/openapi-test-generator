"""Bounded declarative expected-value expressions; never eval user code."""
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
OPS = {'add', 'sub', 'mul', 'div', 'round', 'coalesce', 'if', 'eq', 'sum', 'count', 'min', 'max', 'string'}


class MissingValue(ValueError):
    pass


def read_path(value, path):
    if path in ('', '$'):
        return value
    parts = path.replace('[]', '.*').split('.')
    def walk(node, remaining):
        if not remaining:
            return node
        key, *tail = remaining
        if key == '*':
            if not isinstance(node, list):
                raise MissingValue('配列でない参照: ' + path)
            return [walk(item, tail) for item in node]
        if isinstance(node, dict) and key in node:
            return walk(node[key], tail)
        if isinstance(node, list) and key.isdigit() and int(key) < len(node):
            return walk(node[int(key)], tail)
        raise MissingValue('値がない参照: ' + path)
    return walk(value, parts)


def validate_expr(expr, names=(), depth=0, roots=('body', 'query', 'path', 'steps', 'point')):
    if depth > 20 or not isinstance(expr, dict):
        raise ValueError('計算式は20段階以内の式を指定してください')
    if set(expr) == {'literal'}:
        json.dumps(expr['literal'], allow_nan=False)
    elif set(expr) == {'ref'}:
        ref = expr['ref']
        if not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\[\]|\.[A-Za-z_0-9]+)*', ref) or ref.split('.')[0] not in roots:
            raise ValueError('参照はbody/query/path/stepsから指定してください')
        if ref.startswith('steps.') and ref.split('.')[1].split('[')[0] not in names:
            raise ValueError('参照する処理は先に定義してください: ' + ref)
    elif set(expr) == {'op', 'args'} and expr['op'] in OPS and isinstance(expr['args'], list):
        arity = {'add': 2, 'sub': 2, 'mul': 2, 'div': 2, 'round': 2, 'if': 3, 'eq': 2, 'sum': 1, 'count': 1, 'min': 1, 'max': 1, 'string': 1}
        if len(expr['args']) != arity.get(expr['op'], len(expr['args'])) or not 1 <= len(expr['args']) <= 20:
            raise ValueError('計算の入力数を確認してください')
        for child in expr['args']:
            validate_expr(child, names, depth + 1, roots)
    else:
        raise ValueError('未対応の計算式です')


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('計算には数値が必要です')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('有限数値が必要です')
    return result


def evaluate(expr, context):
    if 'literal' in expr:
        return expr['literal']
    if 'ref' in expr:
        return read_path(context, expr['ref'])
    op, args = expr['op'], expr['args']
    if op == 'coalesce':
        for item in args:
            try:
                value = evaluate(item, context)
            except MissingValue:
                continue
            if value is not None:
                return value  # Preserve false, zero and empty strings.
        raise MissingValue('優先順に指定した値がすべて未設定です')
    if op == 'if':
        condition = evaluate(args[0], context)
        if type(condition) is not bool:
            raise ValueError('条件は真偽値にしてください')
        return evaluate(args[1 if condition else 2], context)
    values = [evaluate(item, context) for item in args]
    if op == 'string':
        if isinstance(values[0], (dict, list)) or values[0] is None:
            raise ValueError('文字列化する値は単一の値にしてください')
        return str(values[0]).lower() if isinstance(values[0], bool) else str(values[0])
    if op == 'eq':
        return equal(values[0], values[1])
    if op in {'sum', 'count', 'min', 'max'}:
        if not isinstance(values[0], list):
            raise ValueError('集計には配列が必要です')
        if op == 'count':
            return len(values[0])
        nums = [number(v) for v in values[0]]
        if op == 'sum':
            return sum(nums, Decimal(0))
        if not nums:
            raise ValueError('空配列の最小・最大は未定義です')
        return min(nums) if op == 'min' else max(nums)
    a, b = map(number, values)
    try:
        if op == 'add': result = a + b
        elif op == 'sub': result = a - b
        elif op == 'mul': result = a * b
        elif op == 'div': result = a / b
        elif op == 'round':
            if b != int(b) or not -12 <= b <= 12:
                raise ValueError('丸めの桁数は-12〜12の整数です')
            result = a.quantize(Decimal(1).scaleb(-int(b)), rounding=ROUND_HALF_UP)
        else: raise ValueError('未対応の演算')
    except (ArithmeticError, InvalidOperation) as exc:
        raise ValueError('数値計算ができません（ゼロ除算等）') from exc
    if not result.is_finite():
        raise ValueError('計算結果が有限数値ではありません')
    return result


def canonical(value):
    if type(value) is bool:
        return ('bool', value)
    if isinstance(value, (int, float, Decimal)):
        return ('number', number(value))
    if isinstance(value, str):
        return ('str', str(value))
    if isinstance(value, dict):
        return ('object', tuple(sorted((k, canonical(v)) for k, v in value.items())))
    if isinstance(value, list):
        return ('array', tuple(map(canonical, value)))
    return (type(value).__name__, value)


def equal(left, right, ordered=True):
    if not ordered and isinstance(left, list) and isinstance(right, list):
        return Counter(map(canonical, left)) == Counter(map(canonical, right))
    return canonical(left) == canonical(right)


def validate_query(query, names):
    if not isinstance(query, dict) or set(query) - {'engine', 'table', 'columns', 'filters', 'order_by'}:
        raise ValueError('DB参照の設定を確認してください')
    if query.get('engine') not in {'postgres', 'influxdb'}:
        raise ValueError('参照元DBを選択してください')
    if not isinstance(query.get('filters', []), list) or not isinstance(query.get('order_by', []), list):
        raise ValueError('検索条件と並び順は配列で指定してください')
    if not isinstance(query.get('columns'), list) or not query['columns'] or not all(isinstance(c, str) for c in query['columns']) or len(set(query['columns'])) != len(query['columns']):
        raise ValueError('取得カラムは重複なく1件以上指定してください')
    for key in [query.get('table'), *query['columns'], *query.get('order_by', [])]:
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            raise ValueError('DB名は英数字・アンダースコアで指定してください')
    for item in query.get('filters', []):
        if not isinstance(item, dict) or set(item) != {'column', 'operator', 'value'} or not isinstance(item['column'], str) or not IDENT.fullmatch(item['column']) or item['operator'] not in {'=', '!=', '>', '>=', '<', '<=', 'in'}:
            raise ValueError('検索条件を確認してください')
        validate_expr(item['value'], names, roots=('body', 'query', 'path', 'steps'))
    if query['engine'] == 'influxdb' and query.get('order_by') not in (None, [], ['time']):
        raise ValueError('InfluxDBの順序はtimeのみ指定できます')


def validate_rules(rules):
    if not isinstance(rules, dict) or set(rules) != {'steps', 'assertions'} or not isinstance(rules['steps'], list) or not isinstance(rules['assertions'], list):
        raise ValueError('期待値ルールには処理と照合項目が必要です')
    if len(rules['steps']) > 20 or not 1 <= len(rules['assertions']) <= 30:
        raise ValueError('処理は20件以内、照合は1〜30件で指定してください')
    names = []
    for step in rules['steps']:
        if not isinstance(step, dict):
            raise ValueError('処理の設定が不正です')
        name = step.get('name', '')
        if not isinstance(name, str) or not IDENT.fullmatch(name) or name in names:
            raise ValueError('処理名は重複しない英数字・アンダースコアで指定してください')
        if set(step) == {'name', 'query'}:
            validate_query(step['query'], names)
        elif set(step) == {'name', 'value'}:
            validate_expr(step['value'], names, roots=('body', 'query', 'path', 'steps'))
        elif set(step) == {'name', 'aggregate'}:
            agg = step['aggregate']
            if not isinstance(agg, dict) or set(agg) != {'source', 'group_by', 'column', 'operation', 'output'} or agg['operation'] not in {'sum', 'count', 'min', 'max'}:
                raise ValueError('集計の設定が不正です')
            if not isinstance(agg['group_by'], list) or not all(isinstance(k, str) for k in agg['group_by']) or len(set(agg['group_by'])) != len(agg['group_by']):
                raise ValueError('グループ列は重複しない配列にしてください')
            validate_expr(agg['source'], names, roots=('body', 'query', 'path', 'steps'))
            for key in [*agg['group_by'], agg['column'], agg['output']]:
                if not isinstance(key, str) or not IDENT.fullmatch(key):
                    raise ValueError('集計カラムを確認してください')
            if agg['output'] in agg['group_by']:
                raise ValueError('集計結果名がグループ列と重複しています')
        else:
            raise ValueError('処理は参照・計算・集計のいずれかを指定してください')
        names.append(name)
    for assertion in rules['assertions']:
        if not isinstance(assertion, dict) or set(assertion) - {'query', 'path', 'expected', 'ordered', 'value_path'} or ('query' in assertion) == ('path' in assertion):
            raise ValueError('照合先はDBまたはレスポンス項目を指定してください')
        validate_expr(assertion.get('expected'), names, roots=('body', 'query', 'path', 'steps'))
        if 'value_path' in assertion and ('query' not in assertion or not isinstance(assertion['value_path'], str)):
            raise ValueError('DB照合の取得値パスが不正です')
        if 'query' in assertion:
            validate_query(assertion['query'], names)
        elif not isinstance(assertion['path'], str):
            raise ValueError('レスポンス項目を指定してください')
        if type(assertion.get('ordered', True)) is not bool:
            raise ValueError('配列順の設定が不正です')
    return rules
