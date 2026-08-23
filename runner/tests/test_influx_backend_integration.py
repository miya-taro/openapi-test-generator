"""influx_backend.py の統合テスト。

ユニットテスト（test_influx_backend.py）は InfluxDBClient 自体をモックしているが、
ここでは pytest-httpserver で実際の HTTP サーバーを立て、InfluxDB 1.x の実際の
/query レスポンス形式（"results" > "series" > "columns"/"values"）を返すことで、
InfluxDBClient のクエリ組み立て～HTTPリクエスト～JSONパースまでを実プロトコルで検証する。
"""
from __future__ import annotations
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_backends import influx_backend
from db_scenario import DBCheck


def _query_response(measurement: str, columns: list[str], values: list[list]) -> dict:
    return {
        "results": [
            {"statement_id": 0, "series": [{"name": measurement, "columns": columns, "values": values}]}
        ]
    }


def _empty_response() -> dict:
    return {"results": [{"statement_id": 0}]}


def _db_config(httpserver) -> dict:
    parsed = urlparse(httpserver.url_for(""))
    return {"host": parsed.hostname, "port": parsed.port, "database": "metrics"}


def test_check_passes_against_real_influxdb_1x_response_format(httpserver):
    httpserver.expect_request("/query").respond_with_json(
        _query_response("sensor_data", ["time", "device_id", "temperature"], [["2026-01-01T00:00:00Z", "abc123", 23.5]])
    )
    check = DBCheck(
        engine="influxdb", measurement="sensor_data", tags={"device_id": "abc123"},
        expect={"exists": True, "fields": {"temperature": 23.5}},
    )

    ok, detail = influx_backend.check(check, _db_config(httpserver))
    assert ok is True, detail


def test_check_fails_when_no_series_in_real_response_format(httpserver):
    httpserver.expect_request("/query").respond_with_json(_empty_response())
    check = DBCheck(engine="influxdb", measurement="sensor_data", tags={"device_id": "nope"}, expect={"exists": True})

    ok, detail = influx_backend.check(check, _db_config(httpserver))
    assert ok is False
    assert "見つかりません" in detail


def test_check_detects_field_mismatch_from_real_response(httpserver):
    httpserver.expect_request("/query").respond_with_json(
        _query_response("sensor_data", ["time", "device_id", "temperature"], [["2026-01-01T00:00:00Z", "abc123", 99.9]])
    )
    check = DBCheck(
        engine="influxdb", measurement="sensor_data", tags={"device_id": "abc123"},
        expect={"exists": True, "fields": {"temperature": 23.5}},
    )

    ok, detail = influx_backend.check(check, _db_config(httpserver))
    assert ok is False
    assert "temperature" in detail


def test_query_sent_to_server_contains_expected_clauses(httpserver):
    httpserver.expect_request("/query").respond_with_json(_empty_response())
    check = DBCheck(engine="influxdb", measurement="sensor_data", tags={"device_id": "abc123"}, time_range="10m", expect={})

    influx_backend.check(check, _db_config(httpserver))

    received = httpserver.log[0][0]
    query = received.args.get("q", "")
    assert "sensor_data" in query
    assert "device_id" in query
    assert "abc123" in query
    assert "10m" in query
