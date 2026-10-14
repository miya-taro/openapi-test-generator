"""Explicit disposable data in a previously empty, user-selected test scope."""
from contextlib import closing

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, Json

from config_loader import get_postgres_config, get_influxdb_config
from db_backends import influx_mutation, influx_response
from db_introspect import introspect_schema
from src.rule_test import validate_fixture


class FixtureUnavailable(Exception):
    pass


def _predicate(scope):
    return sql.SQL(' AND ').join(sql.SQL('{} = %s').format(sql.Identifier(k)) for k in scope)


def _pg_rows(conn, spec, limit=101):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql.SQL('SELECT * FROM {} WHERE {} LIMIT %s').format(
            sql.Identifier(spec['table']), _predicate(spec['scope'])), [*spec['scope'].values(), limit])
        return [dict(row) for row in cur.fetchall()]


def _influx_rows(config, spec):
    with influx_response._client(config) as client:
        tags = {row['tagKey'] for row in client.query(f'SHOW TAG KEYS FROM {influx_response._quote_ident(spec["table"])}').get_points()}
        if tags and tags != set(spec['scope']):
            raise FixtureUnavailable('対象measurementの全タグを指定してください')
        return influx_response._select(client, spec['table'], [(k, '=', v) for k, v in spec['scope'].items()], 101)


def prepare(spec, config, state):
    validate_fixture(spec)
    state.update(definition=spec, setup_status='未確認', cleanup_status='未実施', inserted_keys=[], points=[])
    if spec['engine'] == 'postgres':
        pg = get_postgres_config(config)
        info = introspect_schema(pg, tables=[spec['table']]).get(spec['table'])
        if info is None or not info.primary_key:
            raise FixtureUnavailable('検証テーブルと主キーが必要です')
        known = {column.name: column for column in info.columns}
        if any(key not in known for key in spec['scope']) or any(set(row) - set(known) for row in spec['rows']):
            raise FixtureUnavailable('検証データに存在しないDB列が指定されています')
        with closing(psycopg2.connect(**pg)) as conn:
            with conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute("SET LOCAL statement_timeout = '10s'")
                    # No concurrent inserts between the emptiness check and seed insertion.
                    cur.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(sql.Identifier(spec['table'])))
                    if _pg_rows(conn, spec, 1):
                        raise FixtureUnavailable('専用範囲に既存データがあります。上書きせずHTTP実行前に停止しました')
                    for row in spec['rows']:
                        values = [Json(v) if known[k].data_type in ('json', 'jsonb') and v is not None else v for k, v in row.items()]
                        cur.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING *').format(
                            sql.Identifier(spec['table']), sql.SQL(',').join(map(sql.Identifier, row)),
                            sql.SQL(',').join(sql.Placeholder() for _ in row)), values)
                        inserted = dict(cur.fetchone())
                        state['inserted_keys'].append({key: inserted[key] for key in info.primary_key})
                    actual = _pg_rows(conn, spec)
                    if len(actual) != len(spec['rows']):
                        raise FixtureUnavailable('投入した行数が一致しません（トリガー等を確認してください）')
                    state['prepared_rows'] = actual
                    # The transaction may commit even if its acknowledgement is lost.
                    state['armed'] = True
    else:
        influx = get_influxdb_config(config)
        if _influx_rows(influx, spec):
            raise FixtureUnavailable('専用タグ範囲に既存データがあります。上書きせずHTTP実行前に停止しました')
        for row in spec['rows']:
            fields = {k: {'type': spec['field_types'][k], 'value': v} for k, v in row.items()
                      if k not in spec['scope'] and k != 'time'}
            check = {'measurement': spec['table'], 'time': row['time'], 'tags': spec['scope'],
                     'action': 'delete', 'fields': {}, 'fixture': {'fields': fields}}
            point = {'check': check}
            state['points'].append(point)
            state['armed'] = True
            influx_mutation.begin_fixture(check, influx, point)
        actual = _influx_rows(influx, spec)
        if len(actual) != len(spec['rows']):
            raise FixtureUnavailable('投入したポイント数が一致しません')
        state['prepared_rows'] = actual
        state['armed'] = True
    state['setup_status'] = 'OK'


def cleanup(spec, config, state):
    if not state.get('armed'):
        state['cleanup_status'] = '対象外'
        return
    if spec['engine'] == 'postgres':
        with closing(psycopg2.connect(**get_postgres_config(config))) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL lock_timeout = '3s'")
                    cur.execute("SET LOCAL statement_timeout = '10s'")
                    for key in reversed(state['inserted_keys']):
                        identity = {**key, **spec['scope']}
                        cur.execute(sql.SQL('DELETE FROM {} WHERE {}').format(
                            sql.Identifier(spec['table']), _predicate(identity)), list(identity.values()))
                    moved = False
                    for key in state['inserted_keys']:
                        cur.execute(sql.SQL('SELECT 1 FROM {} WHERE {} LIMIT 1').format(
                            sql.Identifier(spec['table']), _predicate(key)), list(key.values()))
                        moved |= cur.fetchone() is not None
                remaining = _pg_rows(conn, spec, 1)
                remaining = remaining or moved
    else:
        influx = get_influxdb_config(config)
        for point in reversed(state['points']):
            influx_mutation.cleanup_fixture(point['check'], influx, point)
        remaining = _influx_rows(influx, spec)
    if remaining:
        state['remaining_data'] = remaining
        state['cleanup_status'] = 'NG'
        raise FixtureUnavailable('専用範囲に作成行以外のデータが残っています。自動削除せず停止しました')
    state['cleanup_status'] = 'OK'
