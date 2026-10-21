"""Read-only execution of explicit expected-value rules before/after the API."""
from collections import defaultdict
from contextlib import closing
from copy import deepcopy
import json

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from config_loader import get_postgres_config, get_influxdb_config
from db_backends import influx_response
from db_backends.postgres_backend import DBResponseCheckUnverified
from src.expectation_rules import validate_rules, evaluate, read_path, canonical, equal

MAX_ROWS = 5000


def sensitive(definition, previous=()):
    text = json.dumps(definition, ensure_ascii=False).lower().replace('-', '_')
    markers = ('password', 'passwd', 'token', 'secret', 'authorization', 'cookie', 'credential', 'api_key', 'apikey', 'access_key')
    return any(key in text for key in markers) or any('steps.' + name.lower() in text for name in previous)



def read(query, context, config):
    predicates = [(f['column'], f['operator'], evaluate(f['value'], context)) for f in query.get('filters', [])]
    if query['engine'] == 'influxdb':
        with influx_response._client(get_influxdb_config(config)) as client:
            influx_response._validate_columns(client, query['table'], [*query['columns'], *(p[0] for p in predicates)])
            rows = influx_response._select(client, query['table'], predicates, MAX_ROWS + 1)
        rows = [{key: row.get(key) for key in query['columns']} for row in rows]
    else:
        with closing(psycopg2.connect(**get_postgres_config(config))) as connection:
            connection.set_session(readonly=True)
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SET LOCAL statement_timeout = '30s'")
                clauses, values = [], []
                for key, op, value in predicates:
                    if op == 'in':
                        if not isinstance(value, list) or len(value) > MAX_ROWS:
                            raise ValueError('IN検索には5000件以内の配列が必要です')
                        clauses.append(sql.SQL('{} = ANY(%s)').format(sql.Identifier(key)))
                        values.append(value)
                    elif value is None:
                        if op not in {'=', '!='}:
                            raise ValueError('NULLには等価条件のみ指定できます')
                        clauses.append(sql.SQL('{} IS {}NULL').format(sql.Identifier(key), sql.SQL('NOT ' if op == '!=' else '')))
                    else:
                        if isinstance(value, (list, dict)):
                            raise ValueError('検索値は単一の値にしてください')
                        clauses.append(sql.SQL('{} {} %s').format(sql.Identifier(key), sql.SQL(op)))
                        values.append(value)
                statement = sql.SQL('SELECT {} FROM {}').format(sql.SQL(',').join(map(sql.Identifier, query['columns'])), sql.Identifier(query['table']))
                if clauses:
                    statement += sql.SQL(' WHERE ') + sql.SQL(' AND ').join(clauses)
                if query.get('order_by'):
                    statement += sql.SQL(' ORDER BY ') + sql.SQL(',').join(map(sql.Identifier, query['order_by']))
                statement += sql.SQL(' LIMIT 5001')
                cursor.execute(statement, values)
                rows = [dict(row) for row in cursor.fetchall()]
    if len(rows) > MAX_ROWS:
        raise DBResponseCheckUnverified('期待値参照が5000件を超えました。切り捨てて照合しません')
    return rows


def prepare(rules, context, config, evidence):
    validate_rules(rules)
    context = deepcopy(context)
    context['steps'] = {}
    evidence.update(steps=[], assertions=[], verdict='未確認')
    secret_steps = []
    for step in rules['steps']:
        if 'query' in step:
            value = read(step['query'], context, config)
        elif 'value' in step:
            value = evaluate(step['value'], context)
        else:
            agg = step['aggregate']
            source = evaluate(agg['source'], context)
            if not isinstance(source, list):
                raise ValueError('集計元は行の配列が必要です')
            groups = defaultdict(list)
            keys = {}
            for row in source:
                key = tuple(canonical(row[k]) for k in agg['group_by'])
                keys[key] = {k: row[k] for k in agg['group_by']}
                groups[key].append(row[agg['column']])
            value = [{**keys[key], agg['output']: evaluate({'op': agg['operation'], 'args': [{'literal': items}]}, {})}
                     for key, items in groups.items()]
        context['steps'][step['name']] = value
        hidden = sensitive(step, secret_steps)
        if hidden:
            secret_steps.append(step['name'])
        evidence['steps'].append({'name': step['name'], 'value': '[REDACTED]' if hidden else value})
    expected = [deepcopy(evaluate(a['expected'], context)) for a in rules['assertions']]
    return context, expected, [sensitive(a, secret_steps) for a in rules['assertions']]


def verify(rules, prepared, response, config, evidence):
    context, expected, hidden_values = prepared
    failures = []
    for assertion, wanted, hidden in zip(rules['assertions'], expected, hidden_values, strict=True):
        record = {'definition': {'path': '[REDACTED]'} if hidden else assertion, 'expected': '[REDACTED]' if hidden else wanted, 'verdict': '未確認'}
        evidence['assertions'].append(record)
        try:
            actual = read(assertion['query'], context, config) if 'query' in assertion else read_path(response, assertion['path'])
            if 'value_path' in assertion:
                actual = read_path(actual, assertion['value_path'])
            ok = equal(wanted, actual, assertion.get('ordered', True))
            record.update(actual='[REDACTED]' if hidden else actual, verdict='OK' if ok else 'NG')
            if not ok:
                failures.append('期待値ルール: ' + assertion.get('path', assertion.get('query', {}).get('table', 'DB')) + ' が一致しません')
        except Exception as exc:
            record.update(verdict='NG', detail='照合できません（機密項目）' if hidden else str(exc))
            failures.append('期待値ルールの照合に失敗: ' + record['detail'])
    evidence['verdict'] = 'NG' if failures else 'OK'
    return not failures, '; '.join(failures)
