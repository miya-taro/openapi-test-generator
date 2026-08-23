import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_backends import influx_backend
from db_scenario import DBCheck

DB_CONFIG = {"host": "localhost", "port": 8086, "database": "metrics", "username": "u", "password": "p"}


def make_mock_client(points: list[dict]):
    mock_result = MagicMock()
    mock_result.get_points.return_value = points

    mock_client = MagicMock()
    mock_client.query.return_value = mock_result
    return mock_client


# ---------- クエリ組み立て・接続 ----------


def test_check_builds_query_and_calls_client_with_config():
    mock_client = make_mock_client([{"temperature": 23.5}])
    check = DBCheck(
        engine="influxdb", measurement="sensor_data", tags={"device_id": "abc123"},
        time_range="5m", expect={"fields": {"temperature": 23.5}},
    )

    with patch("db_backends.influx_backend.InfluxDBClient", return_value=mock_client) as mock_cls:
        ok, detail = influx_backend.check(check, DB_CONFIG)

    mock_cls.assert_called_once_with(
        host="localhost", port=8086, username="u", password="p", database="metrics"
    )
    query = mock_client.query.call_args[0][0]
    assert "sensor_data" in query
    assert "device_id" in query
    assert "abc123" in query
    assert "5m" in query
    assert ok is True
    mock_client.close.assert_called_once()


def test_check_default_time_range_when_not_specified():
    mock_client = make_mock_client([{"v": 1}])
    check = DBCheck(engine="influxdb", measurement="m", tags={}, expect={})

    with patch("db_backends.influx_backend.InfluxDBClient", return_value=mock_client):
        influx_backend.check(check, DB_CONFIG)

    query = mock_client.query.call_args[0][0]
    assert "now() - 5m" in query


def test_check_rejects_invalid_time_range():
    with pytest.raises(ValueError):
        influx_backend._build_query(
            DBCheck(engine="influxdb", measurement="m", time_range="5; DROP", expect={})
        )


def test_check_rejects_invalid_measurement_identifier():
    with pytest.raises(ValueError):
        influx_backend._build_query(
            DBCheck(engine="influxdb", measurement="m; DROP MEASUREMENT x", expect={})
        )


def test_check_no_measurement_fails_gracefully():
    ok, detail = influx_backend.check(DBCheck(engine="influxdb", expect={}), DB_CONFIG)
    assert ok is False
    assert "measurement" in detail


def test_escape_value_escapes_single_quote():
    assert influx_backend._escape_value("o'brien") == "o\\'brien"


# ---------- 比較ロジック ----------


def test_compare_point_exists_and_fields_match():
    ok, detail = influx_backend._compare([{"temperature": 23.5}], {"exists": True, "fields": {"temperature": 23.5}})
    assert ok is True


def test_compare_no_points_when_expected_fails():
    ok, detail = influx_backend._compare([], {"exists": True})
    assert ok is False
    assert "見つかりません" in detail


def test_compare_points_exist_when_should_not():
    ok, detail = influx_backend._compare([{"v": 1}], {"exists": False})
    assert ok is False


def test_compare_field_mismatch():
    ok, detail = influx_backend._compare([{"temperature": 20.0}], {"exists": True, "fields": {"temperature": 23.5}})
    assert ok is False
    assert "temperature" in detail


def test_compare_missing_field_reported():
    ok, detail = influx_backend._compare([{"other": 1}], {"exists": True, "fields": {"temperature": 23.5}})
    assert ok is False
    assert "存在しません" in detail
