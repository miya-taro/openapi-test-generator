import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(not (os.environ.get('OTG_INTEGRATION_DB_CONFIG') and os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG')),
                    reason='requires dedicated PostgreSQL and InfluxDB 1.x')
def test_explicit_rules_and_bulk_with_real_databases(tmp_path):
    from docs.run_advanced_db_lab import run
    config = {'postgres': json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']),
              'influxdb': json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG'])}
    output = Path(os.environ.get('OTG_ADVANCED_LAB_EVIDENCE_DIR', str(tmp_path / 'advanced-lab')))
    result = run(config, output)
    assert len(result['runs']) == 27
    assert sum(r['expected'] == 'passed' for r in result['runs']) == 10
    assert all(row['matched'] for row in result['runs'])
    assert result['fixtureErrors'] == [] and result['cleanupComplete']
    for row in result['runs']:
        assert 'fixture-password-only' not in (output / row['evidence']).read_text()
