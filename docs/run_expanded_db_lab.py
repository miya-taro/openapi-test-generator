#!/usr/bin/env python3
"""Execute boundary and atomicity qualifications through the native pytest runner."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'runner')]
from docs.expanded_db_lab import ExpandedDatabaseLab, matrix
from docs.run_db_lab import execute, write


def run(config, output):
    output.mkdir(parents=True, exist_ok=False)
    summary = {'startedAt': datetime.now(timezone.utc).isoformat(), 'runs': [], 'fixtureErrors': [], 'cleanupComplete': False}
    for name in ('expanded_db_lab.py', 'run_expanded_db_lab.py'):
        source = (ROOT / 'docs' / name).read_bytes()
        (output / name).write_bytes(source)
        summary.setdefault('sourceFiles', {})['docs/' + name] = hashlib.sha256(source).hexdigest()
    lab = ExpandedDatabaseLab(config)
    try:
        config_path, auth_path = output / 'db-config.json', output / 'auth.json'
        write(config_path, lab.config)
        write(auth_path, {'login_url': '/v1/auth/login', 'method': 'POST',
            'body': {'username': 'fixture-user', 'password': 'fixture-password-only'},
            'token_path': 'id', 'header_name': 'auth-key', 'header_format': '{token}'})
        write(output / 'connection.json', {'recordsTable': lab.records, 'sitesTable': lab.sites,
                                         'influxDatabase': lab.config['influxdb']['database']})
        api, cases = matrix(lab)
        for label, definition, faults, prepare in cases:
            for suffix, fault in [('normal', None), *((f, f) for f in faults)]:
                lab.reset(); lab.fault = fault
                if prepare: prepare()
                result = execute(output, label + '-' + suffix, [definition], api, config_path, auth_path, lab.url,
                                 'failed' if fault else 'passed')
                # A failure caused by an unrelated malformed response is not
                # evidence that the injected database fault was detected.
                if fault:
                    case = json.loads((output / result['evidence']).read_text())['cases'][0]
                    evidence = case['evidence']
                    section = ('db_unchanged' if fault in {'batch-guard', 'partial-commit'} else
                               'influx_mutation' if label.startswith('bulk-') else 'expectation_rules')
                    checks = evidence.get(section, [])
                    checks = checks if isinstance(checks, list) else [checks]
                    result['faultDetectedBy'] = section
                    result['matched'] = result['matched'] and any(c.get('verdict') == 'NG' for c in checks)
                summary['runs'].append(result)
                write(output / 'summary.json', summary)
        summary['fixtureErrors'] = lab.errors
        summary['httpRequests'] = len(lab.calls)
    finally:
        lab.close()
        summary['cleanupComplete'] = True
        summary['finishedAt'] = datetime.now(timezone.utc).isoformat()
        summary['counts'] = dict(Counter(r['expected'] if r['matched'] else 'mismatch' for r in summary['runs']))
        write(output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    summary = run(json.loads(Path(args.config).read_text()), Path(args.output))
    print(json.dumps(summary['counts']))
    raise SystemExit(0 if summary['runs'] and all(row['matched'] for row in summary['runs']) and not summary['fixtureErrors'] else 1)
