"""Read-only PostgreSQL/InfluxDB snapshots around one contract test request."""
from db_backends import postgres_backend, influx_response
from config_loader import get_postgres_config, get_influxdb_config
from db_scenario import DBUnchangedCheck
from models import RunResult, EXIT_ERROR
from src.db_scope import scopes_for_case


def _snapshot(config, scope):
    if scope.engine == "influxdb":
        return influx_response.snapshot_rows(get_influxdb_config(config), scope)
    # Keep direct callers with an already resolved PostgreSQL config compatible.
    return postgres_backend.snapshot_rows(get_postgres_config(config) if "postgres" in config else config, scope)


def execute_guarded(case, api, db_config, send, evidence):
    scopes = [DBUnchangedCheck(**scope) for scope in scopes_for_case(api, case)]
    if not scopes:
        return send(), []
    records = []
    evidence.append({"caseId": case.id, "scopes": records})
    try:
        for scope in scopes:
            rows = _snapshot(db_config, scope)
            records.append({"table": scope.table, "engine": scope.engine, "columns": scope.columns, "where": scope.where,
                            "time_start": scope.time_start, "time_end": scope.time_end,
                            "before_rows": rows, "before_count": len(rows), "verdict": "未確認"})
    except Exception:
        # Do not expose DB driver exceptions (may contain connection information).
        return RunResult(case, 0, "", {}, 0, EXIT_ERROR, error="DB変更なし確認の事前取得に失敗しました（行数上限・接続・範囲を確認）"), ["DB比較未確認・HTTP未送信"]
    result = send()
    failures = []
    for scope, record in zip(scopes, records, strict=True):
        try:
            rows = _snapshot(db_config, scope)
            unchanged = postgres_backend.unchanged_rows(record["before_rows"], rows)
            record.update(after_rows=rows, after_count=len(rows), verdict="OK" if unchanged else "NG")
            if not unchanged:
                failures.append(f"DB変更なし確認: {scope.table} の行または値が変化しました")
        except Exception:
            failures.append(f"DB変更なし確認: {scope.table} の事後取得に失敗・未確認")
    return result, failures
