"""Independent API implementations for explicit rules and bulk verification.

Uses the isolated PostgreSQL tables / InfluxDB database from DatabaseLab. No
production expectation-rule code is imported to produce service responses.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from docs.db_lab_service import DatabaseLab


class AdvancedDatabaseLab(DatabaseLab):
    def record(self, method, path, body):
        if path != '/v1/records/scale':
            return super().record(method, path, body)
        amount = Decimal(str(body['value'])) * 10
        if self.fault == 'wrong-scale': amount += 1
        if self.fault != 'no-op':
            target = 2 if self.fault == 'wrong-target' else body['id']
            self.sql(f'UPDATE {self.records} SET amount=%s WHERE id=%s', (amount, target))
        return 200, {'amount': float(amount)}

    def measurements(self, body):
        # site_id wins over location_id; this business rule is explicit in cases.
        site = body.get('site_id')
        if site is None or self.fault == 'wrong-priority':
            rows = self.sql(f'SELECT site_id FROM {self.sites} WHERE location_id=%s ORDER BY site_id', (body['location_id'],), fetch=True)
            site = rows[0]['site_id']
        totals = defaultdict(float)
        start, end = (datetime.fromisoformat(body[k].replace('Z', '+00:00')) for k in ('start', 'end'))
        for row in self.influx.query('SELECT * FROM readings').get_points():
            when = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            if row['site_id'] == str(site) and start < when <= end and row['item'] in body['items']:
                totals[row['item']] += row['value']
        data = [{'item': key, 'total': value + (1 if self.fault == 'wrong-total' else 0)} for key, value in totals.items()]
        if self.fault == 'missing': data.pop()
        if self.fault == 'duplicate': data.append(dict(data[0]))
        return 200, {'data': list(reversed(data))}

    def point(self, method, body):
        if self.fault == 'no-op': return 204, None
        selected = []
        for row in self.influx.query('SELECT * FROM readings').get_points():
            when = datetime.fromisoformat(row['time'].replace('Z', '+00:00'))
            start, end = (datetime.fromisoformat(body[k].replace('Z', '+00:00')) for k in ('start', 'end'))
            site = '22' if self.fault == 'wrong-target' else body['site_id']
            if start <= when <= end and row['site_id'] == site and row['item'] == body['item']:
                selected.append(row)
        if self.fault == 'missing': selected = selected[:-1]
        if self.fault == 'guard':
            selected.extend(list(self.influx.query("SELECT * FROM readings WHERE site_id='99' AND item='temp'").get_points()))
        if method == 'DELETE':
            for row in selected:
                self.influx.query(f"DELETE FROM readings WHERE time='{row['time']}' AND site_id='{row['site_id']}' AND item='{row['item']}'")
        else:
            self.influx.write_points([{'measurement': 'readings', 'time': row['time'],
                'tags': {'site_id': row['site_id'], 'item': row['item']},
                'fields': {'value': row['value'] * body['factor'] + (1 if self.fault == 'wrong-value' else 0)}} for row in selected])
            if self.fault == 'extra':
                self.influx.write_points([{'measurement': 'readings', 'time': body['start'], 'tags': {'site_id': 'extra', 'item': 'temp'}, 'fields': {'value': 10.0}}])
        return 204, None


def definitions(lab):
    def literal(v): return {'literal': v}
    def ref(v): return {'ref': v}
    def calc(op, *args): return {'op': op, 'args': list(args)}
    def query(engine, table, columns, filters=()):
        return {'engine': engine, 'table': table, 'columns': columns,
                'filters': [{'column': col, 'operator': op, 'value': value} for col, op, value in filters]}
    scale = {'name': '入力の10倍をDBへ保存', 'request': {'operationId': 'scale', 'body': {'id': 1, 'value': 1.234}},
        'response_check': {'expect': {'status': 200}}, 'expectation_rules': {
            'steps': [{'name': 'scaled', 'value': calc('mul', ref('body.value'), literal(10))}],
            'assertions': [{'path': 'amount', 'expected': ref('steps.scaled')},
                {'query': query('postgres', lab.records, ['amount'], [('id', '=', ref('body.id'))]), 'value_path': '0.amount', 'expected': ref('steps.scaled')}]
        }}
    summary = {'name': '拠点を参照してInfluxDBの項目別合計を照合',
        'request': {'operationId': 'summary', 'body': {'location_id': 'A', 'start': '2026-01-01T00:00:00Z', 'end': '2026-01-04T00:00:00Z', 'items': ['temp', 'humidity']}},
        'response_check': {'expect': {'status': 200}}, 'expectation_rules': {
            'steps': [
                {'name': 'site', 'query': query('postgres', lab.sites, ['site_id'], [('location_id', '=', ref('body.location_id'))])},
                {'name': 'selected', 'value': calc('string', calc('coalesce', ref('body.site_id'), ref('steps.site.0.site_id')))},
                {'name': 'readings', 'query': query('influxdb', 'readings', ['item', 'value'], [
                    ('site_id', '=', ref('steps.selected')), ('time', '>', ref('body.start')), ('time', '<=', ref('body.end')), ('item', 'in', ref('body.items'))])},
                {'name': 'totals', 'aggregate': {'source': ref('steps.readings'), 'group_by': ['item'], 'column': 'value', 'operation': 'sum', 'output': 'total'}}],
            'assertions': [{'path': 'data', 'expected': ref('steps.totals'), 'ordered': False}]}}
    bulk = {'name': '一括更新と周囲のポイントを照合',
        'request': {'operationId': 'bulkUpdate', 'body': {'site_id': '11', 'item': 'temp', 'start': '2026-01-02T00:00:00Z', 'end': '2026-01-04T00:00:00Z', 'factor': 10}},
        'response_check': {'expect': {'status': 204, 'empty_body': True}}, 'influx_mutation': {
            'measurement': 'readings', 'action': 'update',
            'scope': {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-05T00:00:00Z', 'tags': {}},
            'target': {'start': '2026-01-02T00:00:00Z', 'end': '2026-01-04T00:00:00Z', 'tags': {'site_id': '11', 'item': 'temp'}},
            'fields': {'value': calc('mul', ref('point.value'), ref('body.factor'))}}}
    operations = [('scale', '/v1/records/scale', 'post', 200), ('summary', '/v1/measurements/get', 'get', 200),
                  ('bulkUpdate', '/v1/point', 'put', 204), ('bulkDelete', '/v1/point', 'delete', 204)]
    paths = {}
    for name, path, method, status in operations:
        response = {'description': 'OK'}
        if status == 200: response['content'] = {'application/json': {'schema': {'type': 'object'}}}
        paths.setdefault(path, {})[method] = {'operationId': name, 'requestBody': {'content': {'application/json': {'schema': {'type': 'object'}}}}, 'responses': {str(status): response}}
    api = {'openapi': '3.1.0', 'info': {'title': 'advanced isolated lab', 'version': '1'}, 'paths': paths}
    return api, scale, summary, bulk
