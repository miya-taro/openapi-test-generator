"""Real HTTP + DB qualification, including faults and cleanup of owned resources."""
import json
import os
from pathlib import Path

from influxdb import InfluxDBClient
import openpyxl
import psycopg2
import pytest

requires_databases = pytest.mark.skipif(
    not (os.environ.get('OTG_INTEGRATION_DB_CONFIG') and os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')),
    reason='requires dedicated PostgreSQL and InfluxDB 1.x')


@requires_databases
def test_expanded_api_database_matrix(tmp_path):
    from docs.run_expanded_db_lab import run
    config = {'postgres': json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']),
              'influxdb': json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG'])}
    output = Path(os.environ.get('OTG_EXPANDED_LAB_EVIDENCE_DIR', str(tmp_path / 'expanded-lab')))
    result = run(config, output)
    assert result['counts'] == {'passed': 17, 'failed': 28}
    assert result['fixtureErrors'] == [] and result['cleanupComplete']
    connection = json.loads((output / 'connection.json').read_text())
    with psycopg2.connect(**config['postgres']) as db, db.cursor() as cursor:
        for table in (connection['recordsTable'], connection['sitesTable']):
            cursor.execute('SELECT to_regclass(%s)', (table,))
            assert cursor.fetchone()[0] is None
    with InfluxDBClient(**config['influxdb']) as client:
        assert connection['influxDatabase'] not in {db['name'] for db in client.get_list_database()}
    for row in result['runs']:
        assert row['matched']
        evidence = output / row['evidence']
        assert 'fixture-password-only' not in evidence.read_text()
        book = openpyxl.load_workbook(evidence.with_suffix('.xlsx'))
        try:
            assert book.active.title == '結果サマリー'
            verdicts = [cell.value for cells in book.active.iter_rows(min_row=5, min_col=3, max_col=3) for cell in cells]
            assert ('NG' if row['expected'] == 'failed' else 'OK') in verdicts
        finally:
            book.close()


@requires_databases
@pytest.mark.parametrize('kind', ['division-zero', 'missing-column', 'empty-target', 'indistinguishable-update'])
def test_unverifiable_setup_sends_no_http_and_changes_no_data(kind):
    from copy import deepcopy
    import requests
    from docs.advanced_db_lab import AdvancedDatabaseLab, definitions
    from db_scenario import _parse_scenario
    from db_scenario_runner import _run_scenario
    config = {'postgres': json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']),
              'influxdb': json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG'])}
    lab = AdvancedDatabaseLab(config)
    try:
        api, scale, _, bulk = definitions(lab)
        definition = deepcopy(scale if kind in {'division-zero', 'missing-column'} else bulk)
        if kind == 'division-zero':
            definition['expectation_rules']['steps'][0]['value'] = {'op': 'div', 'args': [{'literal': 1}, {'literal': 0}]}
        elif kind == 'missing-column':
            definition['expectation_rules']['steps'][0] = {'name': 'scaled', 'query': {
                'engine': 'postgres', 'table': lab.records, 'columns': ['column_that_does_not_exist']}}
        elif kind == 'empty-target':
            definition['influx_mutation']['target']['tags']['site_id'] = 'absent'
        else:
            definition['request']['body']['factor'] = 1
        pg_before = lab.sql(f'SELECT * FROM {lab.records} ORDER BY id', fetch=True)
        influx_before = list(lab.influx.query('SELECT * FROM readings').get_points())
        scenario = _parse_scenario(definition, {})
        evidence = {}
        with requests.Session() as session:
            session.headers['auth-key'] = lab.token
            result = _run_scenario(scenario, api, lab.url, lab.config, {}, session, evidence=evidence)
        assert result[0] is False and result[1].startswith('[UNVERIFIED]'), result
        assert lab.calls == [], 'Preparation failure must not send the API request'
        assert lab.sql(f'SELECT * FROM {lab.records} ORDER BY id', fetch=True) == pg_before
        assert list(lab.influx.query('SELECT * FROM readings').get_points()) == influx_before
        assert lab.errors == []
    finally:
        lab.close()
