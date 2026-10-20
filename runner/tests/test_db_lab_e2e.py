"""Real DB lab regression: normal runs pass, broken services fail, nothing is skipped."""
import json
import os
from pathlib import Path
import sys

from influxdb import InfluxDBClient
import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docs.run_db_lab import run


@pytest.mark.skipif(not (os.environ.get('OTG_INTEGRATION_DB_CONFIG') and os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')),
                    reason='requires dedicated PostgreSQL and InfluxDB 1.x')
def test_repeatable_authenticated_database_lab(tmp_path):
    config = {'postgres': json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']),
              'influxdb': json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG'])}
    output = Path(os.environ.get('OTG_DB_LAB_EVIDENCE_DIR', str(tmp_path / 'db-lab')))
    result = run(config, output)
    assert result['counts'] == {'passed': 45, 'failed': 27}
    assert all(row['matched'] for row in result['runs'])
    assert result['fixtureErrors'] == []
    assert result['flowCleanupConfirmed'] and result['cleanupComplete']
    connection = json.loads((output / 'connection.json').read_text())
    with psycopg2.connect(**config['postgres']) as db, db.cursor() as cursor:
        for table in (connection['recordsTable'], connection['sitesTable']):
            cursor.execute('SELECT to_regclass(%s)', (table,))
            assert cursor.fetchone()[0] is None
    with InfluxDBClient(**config['influxdb']) as client:
        assert connection['influxDatabase'] not in {db['name'] for db in client.get_list_database()}
    for row in result['runs']:
        content = (output / row['evidence']).read_text(encoding='utf-8')
        assert 'fixture-password-only' not in content
        assert 'invalid-lab-token' not in content
