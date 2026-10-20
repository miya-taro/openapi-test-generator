"""Explicit lab contracts and DB relations, separate from the service implementation."""
import copy


def obj(fields, required=None):
    return {'type': 'object', 'properties': fields, 'required': list(fields) if required is None else required}


def specifications():
    text = {'type': 'string'}
    record = obj({'id': {'type': 'integer', 'minimum': 1}, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 40},
                  'amount': {'type': 'number', 'minimum': -1000, 'maximum': 1000}, 'enabled': {'type': 'boolean'},
                  'meta': {'type': ['object', 'null']}, 'note': {'type': ['string', 'null']}},
                 ['id', 'name', 'amount', 'enabled'])
    error = obj({'error': text})
    point = obj({'time': {'type': 'string', 'format': 'date-time'}, 'value': {'type': 'number'}})
    filters = obj({'location_id': text, 'start': {'type': 'string', 'format': 'date-time'},
                   'end': {'type': 'string', 'format': 'date-time'}, 'items': {'type': 'array', 'items': text, 'minItems': 1}})
    routes = [
        ('/v1/auth/login', 'post', 'labLogin', obj({'username': text, 'password': text}),
         {'200': obj({'id': text, 'created_datetime': {'type': 'string', 'format': 'date-time'}}), '401': error}),
        ('/v1/records', 'get', 'labList', None, {'200': obj({'data': {'type': 'array', 'items': record}}), '401': error}),
        ('/v1/records', 'post', 'labCreate', record, {'201': obj({'id': {'type': 'integer'}}), '400': error, '401': error, '409': error}),
        ('/v1/records/{id}', 'get', 'labRead', None, {'200': record, '401': error, '404': error}),
        ('/v1/records/{id}', 'put', 'labReplace', record, {'204': None, '400': error, '401': error}),
        ('/v1/records/{id}', 'patch', 'labPatch', {**record, 'required': [], 'minProperties': 1}, {'204': None, '400': error, '401': error}),
        ('/v1/records/{id}', 'delete', 'labDelete', None, {'204': None, '401': error}),
        ('/v1/measurements/get', 'get', 'labMeasurements', filters,
         {'200': obj({'result': {'type': 'array', 'items': obj({'time': {'type': 'string', 'format': 'date-time'},
                                                             'item': text, 'value': {'type': 'number'}})}}), '400': error, '401': error}),
        *[('/v1/point', method, 'labPoint' + method.title(), point if method != 'delete' else obj({'time': point['properties']['time']}),
           {'204': None, '400': error, '401': error}) for method in ('post', 'put', 'patch', 'delete')],
    ]
    spec = {'openapi': '3.1.0', 'info': {'title': 'Disposable DB lab', 'version': '1'}, 'paths': {},
            'components': {'securitySchemes': {'authKey': {'type': 'apiKey', 'in': 'header', 'name': 'auth-key'}}}}
    for path, method, operation, request, responses in routes:
        op = {'operationId': operation, 'responses': {}}
        for status, schema in responses.items():
            response = {'description': 'Lab contract ' + status}
            if schema is not None:
                response['content'] = {'application/json': {'schema': schema}}
            op['responses'][status] = response
        if request is not None:
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': request}}}
        if '{id}' in path:
            op['parameters'] = [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'integer', 'minimum': 1}}]
        if operation != 'labLogin':
            op['security'] = [{'authKey': []}]
        spec['paths'].setdefault(path, {})[method] = op
    return spec


def scenarios(lab):
    fields = {key: key for key in ('id', 'name', 'amount', 'enabled', 'meta', 'note')}
    guard = {'engine': 'postgres', 'table': lab.records, 'columns': list(fields), 'where': {'id': 99}}
    all_guard = {**guard, 'where': {}}

    def case(name, operation, body=None, status=200, identifier=None, **checks):
        request = {'operationId': operation}
        if body is not None:
            request['body'] = body
        if identifier is not None:
            request['path_params'] = {'id': identifier}
        return {'name': name, 'request': request, 'response_check': {'expect': {'status': status}}, **checks}

    def db(identifier, columns=None, exists=True):
        return {'engine': 'postgres', 'table': lab.records, 'where': {'id': identifier},
                'expect': {'exists': exists, **({'columns': columns} if columns is not None else {})}}

    created = {'id': 3, 'name': '新規', 'amount': 12.345, 'enabled': False,
               'meta': {'nested': {'tags': ['a', 'b'], 'count': 0}}, 'note': None}
    replaced = {**created, 'id': 1, 'name': 'replaced', 'amount': -1.25, 'enabled': True}
    normals = [
        case('GET all unordered rows with JSONB and NULL', 'labList', db_response_check={
            'table': lab.records, 'array_path': 'data', 'fields': fields}, db_unchanged=[all_guard]),
        case('GET one row', 'labRead', identifier=1, db_response_check={
            'table': lab.records, 'array_path': None, 'fields': fields,
            'filters': [{'source': 'path', 'parameter': 'id', 'column': 'id', 'operator': '=', 'auto': False}]}),
        case('POST decimal boolean JSONB NULL', 'labCreate', created, 201,
             db_check=db(3, created), db_unchanged=[guard]),
        case('PUT replace all fields', 'labReplace', replaced, 204, 1,
             db_check=db(1, replaced), db_unchanged=[guard]),
        case('PATCH preserve omitted fields and false', 'labPatch', {'enabled': False}, 204, 2,
             db_check=db(2, {'name': 'second', 'amount': -2.5, 'enabled': False, 'meta': {'nested': {'n': 0}}, 'note': 'keep'}),
             db_unchanged=[guard]),
        case('DELETE selected row only', 'labDelete', status=204, identifier=2,
             db_check=db(2, exists=False), db_unchanged=[guard]),
        case('GET missing row 404', 'labRead', status=404, identifier=888, db_unchanged=[all_guard]),
        case('POST duplicate returns 409 without writes', 'labCreate', {**created, 'id': 99}, 409, db_unchanged=[all_guard]),
    ]
    # Each invalid request has its own explicit oracle: 400 and no database change.
    for label, value in [('missing-name', None), ('empty-name', ''), ('wrong-type-name', 123)]:
        body = {**created, 'id': 4, 'name': value}
        if value is None:
            del body['name']
        normals.append(case(label, 'labCreate', body, 400, db_unchanged=[all_guard]))
    normals.append(case('boolean is not numeric', 'labCreate', {**created, 'id': 4, 'amount': True}, 400, db_unchanged=[all_guard]))
    normals.append(case('nullable JSONB and note', 'labCreate', {**created, 'id': 5, 'meta': None}, 201,
                        db_check=db(5, {**created, 'id': 5, 'meta': None}), db_unchanged=[guard]))

    def measure(location, cardinality):
        return case('cross DB ' + location, 'labMeasurements',
                    {'location_id': location, 'start': '2026-01-02T00:00:00Z', 'end': '2026-01-04T00:00:00Z', 'items': ['temp', 'humidity']},
                    db_response_check={'engine': 'influxdb', 'table': 'readings', 'array_path': 'result',
                        'fields': {key: key for key in ('time', 'item', 'value')}, 'filters': [
                            {'source': 'body', 'parameter': 'location_id', 'column': 'site_id', 'operator': 'in' if cardinality == 'many' else '=',
                             'auto': False, 'lookup': {'engine': 'postgres', 'table': lab.sites, 'match_column': 'location_id',
                                'value_column': 'site_id', 'cardinality': cardinality, 'value_type': 'string', 'on_empty': 'empty'}},
                            *[{'source': 'body', 'parameter': key, 'column': column, 'operator': op, 'auto': False}
                              for key, column, op in [('start', 'time', '>'), ('end', 'time', '<='), ('items', 'item', 'in')]]]})
    normals.extend([measure('A', 'one'), measure('MULTI', 'many'), measure('MISSING', 'one')])
    for method, action in [('Post', 'insert'), ('Put', 'update'), ('Patch', 'update'), ('Delete', 'delete')]:
        mutation = {'measurement': 'points', 'time': '2026-01-01T00:00:00Z', 'tags': {'item': 'a'}, 'action': action,
                    'fixture': {'fields': {'value': {'type': 'float', 'value': 1}}}}
        if action == 'insert':
            mutation['fixture'] = {'fields': {}}
        if action != 'delete':
            mutation['fields'] = {'value': 2.5}
        normals.append(case('Influx ' + method, 'labPoint' + method,
                            {'time': mutation['time'], **({'value': 2.5} if action != 'delete' else {})}, 204, influx_mutation=mutation))
    # Real HTTP create -> read generated ID -> cleanup; main assertion reads PostgreSQL.
    flow = case('create read delete lifecycle', 'labRead', identifier='{{steps.create.id}}',
                db_response_check={'table': lab.records, 'array_path': None, 'fields': fields,
                    'filters': [{'source': 'path', 'parameter': 'id', 'column': 'id', 'operator': '=', 'auto': False}]})
    flow['api_flow'] = {'before': [{'name': 'create', 'request': {'operationId': 'labCreate', 'body': {**created, 'id': 70}}, 'expect_status': 201}],
                        'cleanup': [{'name': 'delete', 'request': {'operationId': 'labDelete', 'path_params': {'id': '{{steps.create.id}}'}}, 'expect_status': 204}]}
    normals.append(flow)
    return normals


def faulty_cases(normal):
    # Reuse identical expectations; only the API implementation's behavior changes.
    by_name = {case['name']: case for case in normal}
    targets = {
        'read-value': ['GET all unordered rows with JSONB and NULL', 'cross DB A'],
        'read-missing': ['GET all unordered rows with JSONB and NULL', 'cross DB A'],
        'read-duplicate': ['GET all unordered rows with JSONB and NULL', 'cross DB A'],
        'write-value': ['POST decimal boolean JSONB NULL', 'PUT replace all fields', 'Influx Post', 'Influx Put', 'Influx Patch'],
        'no-op': ['POST decimal boolean JSONB NULL', 'PUT replace all fields', 'DELETE selected row only', 'Influx Post', 'Influx Put', 'Influx Patch', 'Influx Delete'],
        'wrong-target': ['PUT replace all fields', 'DELETE selected row only'],
        'clobber': ['PATCH preserve omitted fields and false'],
        'extra-write': ['POST decimal boolean JSONB NULL'],
        'invalid-write': ['missing-name', 'boolean is not numeric'],
        'first-site': ['cross DB MULTI'],
        'ignore-site': ['cross DB A'],
    }
    for fault, names in targets.items():
        for name in names:
            yield fault, copy.deepcopy(by_name[name])
