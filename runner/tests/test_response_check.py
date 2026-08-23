import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from response_check import check
from db_scenario import ResponseCheck


def test_status_match_passes():
    rc = ResponseCheck(expect_status=200)
    ok, detail = check(rc, 200, {})
    assert ok is True
    assert detail == ""


def test_status_mismatch_fails():
    rc = ResponseCheck(expect_status=200)
    ok, detail = check(rc, 404, {})
    assert ok is False
    assert "期待=200" in detail
    assert "実測=404" in detail


def test_no_expect_status_skips_status_check():
    rc = ResponseCheck(expect_status=None, expect_body={})
    ok, detail = check(rc, 500, {})
    assert ok is True


def test_body_field_match_passes():
    rc = ResponseCheck(expect_body={"price": 99999999.99})
    ok, detail = check(rc, 200, {"price": 99999999.99})
    assert ok is True


def test_body_field_mismatch_fails():
    rc = ResponseCheck(expect_body={"price": 100})
    ok, detail = check(rc, 200, {"price": 200})
    assert ok is False
    assert "price" in detail
    assert "期待=100" in detail
    assert "実測=200" in detail


def test_body_field_missing_fails():
    rc = ResponseCheck(expect_body={"price": 100})
    ok, detail = check(rc, 200, {"other_field": 1})
    assert ok is False
    assert "存在しません" in detail


def test_nested_body_field_dot_path():
    rc = ResponseCheck(expect_body={"user.name": "太郎"})
    ok, detail = check(rc, 200, {"user": {"name": "太郎"}})
    assert ok is True


def test_nested_body_field_dot_path_mismatch():
    rc = ResponseCheck(expect_body={"user.name": "太郎"})
    ok, detail = check(rc, 200, {"user": {"name": "次郎"}})
    assert ok is False
    assert "user.name" in detail


def test_multiple_body_fields_all_must_match():
    rc = ResponseCheck(expect_body={"a": 1, "b": 2})
    ok, detail = check(rc, 200, {"a": 1, "b": 999})
    assert ok is False
    assert "b" in detail
    assert "a" not in detail  # aは一致しているので言及されない


def test_status_and_body_both_checked_and_combined_in_detail():
    rc = ResponseCheck(expect_status=200, expect_body={"price": 100})
    ok, detail = check(rc, 404, {"price": 200})
    assert ok is False
    assert "status" in detail
    assert "price" in detail


def test_empty_expect_body_and_no_status_always_passes():
    rc = ResponseCheck()
    ok, detail = check(rc, 500, {"anything": "goes"})
    assert ok is True
    assert detail == ""


def test_array_index_path_passes():
    rc = ResponseCheck(expect_body={"items.0.price": 750})
    ok, detail = check(rc, 200, {"items": [{"price": 750}, {"price": 500}]})
    assert ok is True


def test_array_index_path_mismatch():
    rc = ResponseCheck(expect_body={"items.0.price": 750})
    ok, detail = check(rc, 200, {"items": [{"price": 999}]})
    assert ok is False
    assert "items.0.price" in detail


def test_array_index_out_of_range_reports_missing():
    rc = ResponseCheck(expect_body={"items.5.price": 750})
    ok, detail = check(rc, 200, {"items": [{"price": 750}]})
    assert ok is False
    assert "存在しません" in detail


def test_array_index_non_numeric_segment_reports_missing():
    rc = ResponseCheck(expect_body={"items.name.price": 750})
    ok, detail = check(rc, 200, {"items": [{"price": 750}]})
    assert ok is False
    assert "存在しません" in detail
