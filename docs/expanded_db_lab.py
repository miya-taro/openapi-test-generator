"""Additional independent HTTP behaviors for boundary and atomic-write checks."""
from copy import deepcopy
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import Json

from docs.advanced_db_lab import AdvancedDatabaseLab, definitions


class ExpandedDatabaseLab(AdvancedDatabaseLab):
    def measurements(self, body):
        body = deepcopy(body)
        if self.fault in {'start-inclusive', 'end-exclusive'}:
            key = 'start' if self.fault == 'start-inclusive' else 'end'
            body[key] = (datetime.fromisoformat(body[key].replace('Z', '+00:00')) - timedelta(microseconds=1)).isoformat()
        if self.fault == 'ignore-items':
            body['items'] = ['temp', 'humidity', 'other']
        status, response = super().measurements(body)
        if self.fault == 'invent-empty':
            response['data'] = [{'item': 'temp', 'total': 0}]
        if self.fault == 'numeric-string':
            for row in response['data']:
                row['total'] = str(row['total'])
        return status, response

    def record(self, method, path, body):
        if path != '/v1/records/batch':
            return super().record(method, path, body)
        rows = body.get('rows') if isinstance(body, dict) else None
        if not isinstance(rows, list) or not rows or not all(self.valid_record(row) for row in rows):
            return 400, {'error': 'invalid batch'}
        columns = ('id', 'name', 'amount', 'enabled', 'meta', 'note')

        def insert(cursor, row):
            cursor.execute(f'INSERT INTO {self.records} VALUES (%s,%s,%s,%s,%s,%s)',
                           tuple(Json(row.get(k)) if k == 'meta' else row.get(k) for k in columns))

        try:
            with psycopg2.connect(**self.config['postgres']) as connection, connection.cursor() as cursor:
                for index, row in enumerate(rows):
                    if self.fault == 'batch-missing' and index == len(rows) - 1:
                        continue
                    row = deepcopy(row)
                    if self.fault == 'batch-value': row['amount'] += 1
                    if self.fault == 'batch-null': row['note'] = ''
                    insert(cursor, row)
                if self.fault == 'batch-extra': insert(cursor, {**rows[0], 'id': 43})
                if self.fault == 'batch-guard': cursor.execute(f'UPDATE {self.records} SET amount=0 WHERE id=99')
        except psycopg2.errors.UniqueViolation:
            # Simulate the common broken behavior: first row commits despite the
            # second row failing. The correct implementation rolls back both.
            if self.fault == 'partial-commit':
                with psycopg2.connect(**self.config['postgres']) as connection, connection.cursor() as cursor:
                    insert(cursor, rows[0])
            return 409, {'error': 'duplicate'}
        return 204, None

    def point(self, method, body):
        status, response = super().point(method, body)
        if self.fault == 'clobber-field':
            self.influx.write_points([{'measurement': 'readings', 'time': body['start'],
                'tags': {'site_id': body['site_id'], 'item': body['item']}, 'fields': {'quality': 'broken'}}])
        return status, response


def matrix(lab):
    """Return explicit oracles; no service code computes these expected results."""
    api, scale, aggregate, bulk = definitions(lab)
    error_body = {'application/json': {'schema': {'type': 'object', 'required': ['error'],
                                                 'properties': {'error': {'type': 'string'}}}}}
    api['paths']['/v1/records/batch'] = {'post': {'operationId': 'batch',
        'requestBody': {'required': True, 'content': {'application/json': {'schema': {'type': 'object'}}}},
        'responses': {'204': {'description': 'All rows committed'},
                      '400': {'description': 'Invalid batch; no writes', 'content': error_body},
                      '409': {'description': 'Duplicate; entire batch rolled back', 'content': error_body}}}}
    cases = []
    for label, value in [('zero', 0), ('negative', -2.345), ('round-up', 0.12345), ('round-negative', -0.12345)]:
        case = deepcopy(scale); case['name'] = 'numeric ' + label
        case['request']['body']['value'] = value
        # The response returns the unrounded number; numeric(15,3) rounds only
        # the stored value. Both expectations are explicit and different.
        case['expectation_rules']['assertions'][1]['expected'] = {
            'op': 'round', 'args': [{'ref': 'steps.scaled'}, {'literal': 3}]}
        cases.append(('scale-' + label, case, ['wrong-scale', 'no-op'], None))

    for label, changes, faults in [
        ('boundaries', {'start': '2026-01-02T00:00:00Z'}, ['start-inclusive', 'end-exclusive']),
        ('timezone', {'start': '2026-01-02T09:00:00+09:00', 'end': '2026-01-04T09:00:00+09:00'}, ['start-inclusive', 'end-exclusive']),
        ('one-item', {'items': ['temp']}, ['ignore-items', 'numeric-string']),
        ('no-matching-item', {'items': ['absent']}, ['invent-empty']),
        ('empty-period', {'start': '2026-02-01T00:00:00Z', 'end': '2026-02-02T00:00:00Z'}, ['invent-empty']),
        ('site-zero', {'site_id': 0}, ['wrong-priority']),
    ]:
        case = deepcopy(aggregate); case['name'] = 'summary ' + label
        case['request']['body'].update(changes)
        cases.append(('summary-' + label, case, faults, None))

    fields = ['id', 'name', 'amount', 'enabled', 'meta', 'note']
    rows = [
        {'id': 41, 'name': '日本語・引用符\' "', 'amount': 0, 'enabled': False, 'meta': {'tags': [], 'nested': {'enabled': False}}, 'note': None},
        {'id': 42, 'name': 'second', 'amount': -12.345, 'enabled': True, 'meta': {'tags': ['a', 'b']}, 'note': '保持'},
    ]
    guard = {'engine': 'postgres', 'table': lab.records, 'columns': fields, 'where': {}}
    batch = {'name': 'atomic batch', 'request': {'operationId': 'batch', 'body': {'rows': rows}},
        'response_check': {'expect': {'status': 204, 'empty_body': True}},
        'db_unchanged': [{**guard, 'where': {'id': 99}}],
        'expectation_rules': {'steps': [], 'assertions': [{
            'query': {'engine': 'postgres', 'table': lab.records, 'columns': fields, 'filters': [
                {'column': 'id', 'operator': '>=', 'value': {'literal': 40}},
                {'column': 'id', 'operator': '<', 'value': {'literal': 99}}]},
            'expected': {'ref': 'body.rows'}, 'ordered': False}]}}
    cases.append(('batch', batch, ['batch-missing', 'batch-value', 'batch-null', 'batch-extra', 'batch-guard'], None))
    for label, value, status, faults in [
        ('rollback', [rows[0], {**rows[1], 'id': 99}], 409, ['partial-commit']),
        ('invalid-last', [rows[0], {**rows[1], 'enabled': 'false'}], 400, []),
        ('empty', [], 400, []),
    ]:
        case = {'name': 'batch ' + label, 'request': {'operationId': 'batch', 'body': {'rows': value}},
                'response_check': {'expect': {'status': status}}, 'db_unchanged': [guard]}
        cases.append(('batch-' + label, case, faults, None))
    for label, factor in [('zero', 0), ('negative', -2)]:
        case = deepcopy(bulk); case['name'] = 'bulk ' + label
        case['request']['body']['factor'] = factor
        cases.append(('bulk-' + label, case, ['wrong-value', 'guard'], None))

    def extra_field():
        lab.influx.write_points([{'measurement': 'readings', 'time': bulk['request']['body']['start'],
            'tags': {'site_id': '11', 'item': 'temp'}, 'fields': {'quality': 'keep'}}])
    cases.append(('bulk-preserve-fields', deepcopy(bulk), ['clobber-field'], extra_field))
    return api, cases
