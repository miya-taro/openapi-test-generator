"""Read an explicit SELECT with bound request values and compare grouped JSON."""
import psycopg2
from psycopg2.extras import RealDictCursor, Json

from config_loader import get_postgres_config
from src.sql_response_mapping import validate_sql_response
from db_backends.postgres_insert import equal
from db_backends.postgres_backend import DBResponseCheckUnverified

MAX_ROWS = 5000
MISSING = object()


def bind_parameters(check, request):
    result = {}
    for name, rule in check.get('parameters', {}).items():
        value = request.get(rule['source'], {})
        for part in rule['path'].split('.'):
            value = value.get(part, MISSING) if isinstance(value, dict) else MISSING
        if value is MISSING:
            if rule.get('missing') != 'null':
                raise ValueError(f'SQLパラメータ {name} のリクエスト項目がありません')
            value = None
        result[name] = value
    return result


def read_rows(check, request, config):
    validate_sql_response(check)
    values = bind_parameters(check, request)
    conn = psycopg2.connect(**get_postgres_config(config))
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
            sql = check['sql'].strip().removesuffix(';')
            adapted = {k: Json(v) if isinstance(v, dict) else v for k, v in values.items()}
            # The SELECT is a subquery, so LIMIT cannot silently truncate a result.
            cur.execute(f'SELECT * FROM ({sql}) AS expected_rows LIMIT {MAX_ROWS + 1}', adapted)
            names = [d.name for d in cur.description]
            if len(names) != len(set(names)):
                raise ValueError('SQL結果の列名が重複しています。ASで別名を指定してください')
            required = set(check['fields'].values()) | {k for a in check.get('arrays', []) for k in a.get('group_by', [])}
            if not required <= set(names):
                raise ValueError('SQL結果に対応付けた列・グループ列がありません')
            rows = [dict(row) for row in cur.fetchall()]
            if len(rows) > MAX_ROWS:
                raise DBResponseCheckUnverified(f'期待値SQLが{MAX_ROWS}行を超えます')
            return rows, values
    finally:
        conn.rollback()
        conn.close()


def expected_tree(check, rows):
    """Grouping preserves parent identity; repeated leaf rows remain repeated."""
    validate_sql_response(check)
    arrays = {a['path']: a for a in check.get('arrays', [])}
    def build(prefix, subset):
        result = {}
        children = {}
        for path in check['fields']:
            if path.startswith(prefix):
                part = path[len(prefix):].split('.')[0]
                children[part] = prefix + part
        for part, path in children.items():
            key = part.removesuffix('[]')
            if part.endswith('[]'):
                config = arrays[path]
                group_keys = config.get('group_by', [])
                groups = []
                for row in subset:
                    identity = [row[k] for k in group_keys]
                    found = next((group for ids, group in groups if group_keys and equal(ids, identity)), None)
                    if found is None:
                        groups.append((identity, [row]))
                    else:
                        found.append(row)
                result[key] = [build(path + '.', group) for _, group in groups]
            elif path in check['fields']:
                if not subset:
                    raise DBResponseCheckUnverified(f'期待値SQLが0行のため {path} の期待値を取得できません')
                column = check['fields'][path]
                value = subset[0][column]
                if not all(equal(row[column], value) for row in subset):
                    raise ValueError(f'{path}: 同じグループ内の値が一致しません。グループ列を見直してください')
                result[key] = value
            else:
                result[key] = build(path + '.', subset)
        return result
    return build('', rows)


def compare(check, expected, actual, evidence):
    arrays = {a['path']: a for a in check.get('arrays', [])}
    mapped = set(check['fields'])
    def matches(wanted, got, path=''):
        if path in mapped:
            return equal(got, wanted)
        if isinstance(wanted, dict):
            return isinstance(got, dict) and all(k in got and matches(v, got[k], f'{path}.{k}' if path else k) for k, v in wanted.items())
        if isinstance(wanted, list):
            array_path = path + '[]'
            if not isinstance(got, list) or len(got) != len(wanted):
                return False
            if arrays[array_path].get('ordered', False):
                return all(matches(a, b, array_path) for a, b in zip(wanted, got, strict=True))
            remaining = list(got)
            for item in wanted:
                index = next((i for i, other in enumerate(remaining) if matches(item, other, array_path)), None)
                if index is None:
                    return False
                remaining.pop(index)
            return True
        return equal(got, wanted)
    ok = matches(expected, actual)
    evidence.update(expected=expected, actual=actual, verdict='OK' if ok else 'NG')
    return ok, 'SQL取得結果と入れ子レスポンスが一致' if ok else 'SQL取得結果とレスポンスが不一致（値・所属グループ・件数・欠落・重複・順序を確認）'
