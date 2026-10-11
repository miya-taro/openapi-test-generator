"""Single-point insertion/update/deletion expectations without writes by the checker."""
from db_backends.influx_response import _client, _select, _quote_ident, DBResponseCheckUnverified, DBResponseCheckError
from src.influx_mutation import validate_mutation


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
