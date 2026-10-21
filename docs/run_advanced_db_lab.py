#!/usr/bin/env python3
"""Qualify explicit expectations and bounded bulk changes with real databases."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'runner')]
from docs.advanced_db_lab import AdvancedDatabaseLab, definitions
from docs.run_db_lab import execute, write


def run(config, output):
    output.mkdir(parents=True, exist_ok=False)
    lab = AdvancedDatabaseLab(config)
    summary = {'runs': []}
    try:
        config_path, auth_path = output / 'db-config.json', output / 'auth.json'
        write(config_path, lab.config)
        write(auth_path, {'login_url': '/v1/auth/login', 'method': 'POST',
            'body': {'username': 'fixture-user', 'password': 'fixture-password-only'},
            'token_path': 'id', 'header_name': 'auth-key', 'header_format': '{token}'})
        api, scale, aggregate, bulk = definitions(lab)
        priority = deepcopy(aggregate)
        priority['name'] = '拠点IDを優先する明示ルール'
        priority['request']['body']['site_id'] = 22
        delete = deepcopy(bulk)
        delete['name'] = '一括削除と周囲のポイントを照合'
        delete['request']['operationId'] = 'bulkDelete'
        delete['influx_mutation'].update(action='delete', fields={})
        cases = [('scale', scale, ['wrong-scale', 'wrong-target', 'no-op']),
                 ('aggregate', aggregate, ['wrong-total', 'missing', 'duplicate']),
                 ('priority', priority, ['wrong-priority']),
                 ('bulk-update', bulk, ['wrong-value', 'wrong-target', 'guard', 'missing', 'extra', 'no-op']),
                 ('bulk-delete', delete, ['wrong-target', 'guard', 'missing', 'no-op'])]
        for label, definition, faults in cases:
            for suffix, fault in [('normal', None), ('repeat', None), *((f, f) for f in faults)]:
                lab.reset(); lab.fault = fault
                result = execute(output, label + '-' + suffix, [definition], api, config_path, auth_path, lab.url,
                                 'failed' if fault else 'passed')
                summary['runs'].append(result)
                write(output / 'summary.json', summary)
        summary['fixtureErrors'] = lab.errors
        summary['httpRequests'] = len(lab.calls)
    finally:
        lab.close()
        summary['cleanupComplete'] = True
        write(output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    summary = run(json.loads(Path(args.config).read_text()), Path(args.output))
    raise SystemExit(0 if all(row['matched'] for row in summary['runs']) and not summary['fixtureErrors'] else 1)
