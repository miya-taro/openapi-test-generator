"""Single-point checks with optional explicit, disposable test fixtures."""
from db_backends.influx_response import _client, _select, _quote_ident, _where, DBResponseCheckUnverified, DBResponseCheckError
from src.influx_mutation import validate_mutation, fixture_timestamp


def _points(config, check):
    validate_mutation(check)
    with _client(config) as client:
        tags = {p['tagKey'] for p in client.query(f'SHOW TAG KEYS FROM {_quote_ident(check["measurement"])}').get_points()}
        # Refuse a partial series identity rather than matching some other point.
        if tags and tags != set(check['tags']):
            raise DBResponseCheckError('対象measurementの全タグを指定してください（タグ構成の異なる系列は初版対象外）')
        specs = [('time', '=', check['time']), *((key, '=', val) for key, val in check['tags'].items())]
        rows = _select(client, check['measurement'], specs, 2)
        if len(rows) > 1:
            raise DBResponseCheckError('ポイント時刻・タグで対象を1件に特定できません')
        return rows


def _same(actual, expected):
    return isinstance(actual, bool) == isinstance(expected, bool) and actual == expected


def begin_fixture(check, config, state):
    """Claim an absent identity only. Never overwrite or restore existing points."""
    validate_mutation(check)
    fields = {key: float(spec['value']) if spec['type'] == 'float' else spec['value']
              for key, spec in check['fixture']['fields'].items()}
    state.update(setup_status='未確認', cleanup_status='対象外', initial_fields=fields)
    if _points(config, check):
        raise DBResponseCheckUnverified('検証用ポイントの時刻・タグに既存データがあります。上書きせず停止しました')
    if check['action'] == 'update' and all(key in fields and _same(fields[key], value) for key, value in check['fields'].items()):
        raise DBResponseCheckUnverified('初期値と更新後の期待値が同じです。異なる初期値を指定してください')
    # Arm before the write: the server may accept it even if its reply is lost.
    state.update(armed=True, cleanup_status='未実施')
    if fields:
        with _client(config) as client:
            if not client.write_points([{'measurement': check['measurement'], 'time': fixture_timestamp(check['time']),
                                         'tags': check['tags'], 'fields': fields}], time_precision='n'):
                raise DBResponseCheckError('検証用ポイントを投入できません')
        actual = _points(config, check)
        if len(actual) != 1 or any(key not in actual[0] or not _same(actual[0][key], value) for key, value in fields.items()):
            raise DBResponseCheckError('投入した検証用ポイントを確認できません')
    state['setup_status'] = 'OK'


def cleanup_fixture(check, config, state):
    if not state.get('armed'):
        return
    # Recheck the complete tag identity before allowing a bounded deletion.
    _points(config, check)
    specs = [('time', '=', check['time']), *((key, '=', val) for key, val in check['tags'].items())]
    with _client(config) as client:
        client.query(f'DELETE FROM {_quote_ident(check["measurement"])} WHERE {_where(specs)}')
    if _points(config, check):
        raise DBResponseCheckError('検証用ポイントが残っています')
    state['cleanup_status'] = 'OK'


def prepare(check, config):
    before = _points(config, check)
    if check['action'] == 'insert' and before:
        raise DBResponseCheckUnverified('保存確認の対象ポイントは既に存在します。新しい時刻・タグを指定してください')
    if check['action'] in ('update', 'delete') and not before:
        raise DBResponseCheckUnverified('更新・削除対象のポイントがありません')
    if check['action'] == 'update' and all(key in before[0] and _same(before[0][key], val) for key, val in check['fields'].items()):
        raise DBResponseCheckUnverified('既存値と期待値が同じため、更新しないAPIを識別できません。異なる試験値を指定してください')
    return {'definition': check, 'before_points': before, 'before_count': len(before), 'verdict': '未確認'}


def verify(check, config, evidence):
    after = _points(config, check)
    evidence.update(after_points=after, after_count=len(after))
    failures = []
    if check['action'] == 'delete':
        if after:
            failures.append('削除後も対象ポイントが存在します')
    elif not after:
        failures.append('保存・更新後の対象ポイントがありません')
    else:
        for key, val in check['fields'].items():
            if key not in after[0] or not _same(after[0][key], val):
                failures.append(f'期待フィールド「{key}」が一致しません')
        if check.get('preserve_unmapped') and evidence['before_points']:
            excluded = {'time', *check['tags'], *check['fields']}
            for key, val in evidence['before_points'][0].items():
                if key not in excluded and (key not in after[0] or not _same(after[0][key], val)):
                    failures.append(f'未指定フィールド「{key}」が変化しました')
    evidence['verdict'] = 'NG' if failures else 'OK'
    return not failures, '; '.join(failures)
