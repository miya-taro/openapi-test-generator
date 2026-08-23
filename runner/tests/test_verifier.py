import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from verifier import verify, PASS, FAIL, WARN
from models import RunCase, RunResult, ResponseSchema


def make_case() -> RunCase:
    return RunCase(
        id="TC-001", operation_id="op", path="/", method="GET",
        param_in="query", param_name="p", input_value="1",
        expected_status="200", expected_response_body="",
        expected_response_header="", expected_response_time="3秒以内",
        expected_result="",
    )


def make_result(
    status: int = 200,
    elapsed_ms: float = 100.0,
    headers: dict | None = None,
    curl_exit_code: int = 0,
    error: str | None = None,
    body: str = "",
) -> RunResult:
    return RunResult(
        case=make_case(),
        actual_status=status,
        actual_body=body,
        actual_headers=headers or {},
        elapsed_ms=elapsed_ms,
        curl_exit_code=curl_exit_code,
        error=error,
    )


def make_schema(
    expected_status: int = 200,
    expected_content_type: str | None = None,
    expected_response_time_ms: float = 3000.0,
    expected_body_schema: dict | None = None,
    expected_headers: dict | None = None,
) -> ResponseSchema:
    return ResponseSchema(
        expected_status=expected_status,
        expected_content_type=expected_content_type,
        expected_response_time_ms=expected_response_time_ms,
        expected_body_schema=expected_body_schema,
        expected_headers=expected_headers or {},
    )


# Level 1: status code

def test_level1_pass():
    verdict, detail = verify(make_result(200), make_schema(200))
    assert verdict == PASS
    assert detail == ""


def test_level1_fail_status_mismatch():
    verdict, detail = verify(make_result(500), make_schema(200))
    assert verdict == FAIL
    assert "ステータス不一致" in detail


def test_level1_fail_on_curl_timeout():
    result = make_result(curl_exit_code=28, error="timeout")
    verdict, detail = verify(result, make_schema(200))
    assert verdict == FAIL
    assert "タイムアウト" in detail


def test_level1_fail_on_curl_error():
    result = make_result(curl_exit_code=7, error="connection refused")
    verdict, detail = verify(result, make_schema(200))
    assert verdict == FAIL
    assert "curl エラー" in detail


# Level 2: response time

def test_level2_warning_on_slow_response():
    result = make_result(status=200, elapsed_ms=4000.0)
    verdict, detail = verify(result, make_schema(200, expected_response_time_ms=3000.0))
    assert verdict == WARN
    assert "応答時間超過" in detail


def test_level2_pass_within_time():
    result = make_result(status=200, elapsed_ms=2999.0)
    verdict, detail = verify(result, make_schema(200, expected_response_time_ms=3000.0))
    assert verdict == PASS


# Level 3: Content-Type

def test_level3_pass_content_type_matches():
    result = make_result(status=200, headers={"Content-Type": "application/json; charset=utf-8"})
    schema = make_schema(200, expected_content_type="application/json")
    verdict, detail = verify(result, schema)
    assert verdict == PASS


def test_level3_fail_content_type_mismatch():
    result = make_result(status=200, headers={"Content-Type": "text/html"})
    schema = make_schema(200, expected_content_type="application/json")
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "Content-Type" in detail


def test_level3_skipped_when_no_expected_ct():
    result = make_result(status=200, headers={})
    schema = make_schema(200, expected_content_type=None)
    verdict, _ = verify(result, schema)
    assert verdict == PASS


# Level 3: Content-Type以外の期待ヘッダ

def test_level3_header_existence_only_passes_regardless_of_value():
    result = make_result(status=200, headers={"X-Total-Count": "42"})
    schema = make_schema(200, expected_headers={"X-Total-Count": None})
    verdict, detail = verify(result, schema)
    assert verdict == PASS


def test_level3_header_missing_fails():
    result = make_result(status=200, headers={})
    schema = make_schema(200, expected_headers={"X-Total-Count": None})
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "ヘッダ不足" in detail
    assert "X-Total-Count" in detail


def test_level3_header_concrete_value_matches_passes():
    result = make_result(status=200, headers={"X-Api-Version": "v1"})
    schema = make_schema(200, expected_headers={"X-Api-Version": "v1"})
    verdict, detail = verify(result, schema)
    assert verdict == PASS


def test_level3_header_concrete_value_mismatch_fails():
    result = make_result(status=200, headers={"X-Api-Version": "v2"})
    schema = make_schema(200, expected_headers={"X-Api-Version": "v1"})
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "X-Api-Version不一致" in detail
    assert "期待=v1" in detail
    assert "v2" in detail


def test_level3_header_lookup_is_case_insensitive():
    result = make_result(status=200, headers={"x-api-version": "v1"})
    schema = make_schema(200, expected_headers={"X-Api-Version": "v1"})
    verdict, _ = verify(result, schema)
    assert verdict == PASS


def test_level3_multiple_expected_headers_all_must_pass():
    result = make_result(status=200, headers={"X-Api-Version": "v1"})  # X-Total-Countが無い
    schema = make_schema(200, expected_headers={"X-Api-Version": "v1", "X-Total-Count": None})
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "X-Total-Count" in detail
    assert "X-Api-Version" not in detail  # 一致している方は言及されない


def test_level3_no_expected_headers_does_not_affect_pass():
    result = make_result(status=200, headers={})
    schema = make_schema(200, expected_headers={})
    verdict, _ = verify(result, schema)
    assert verdict == PASS


# Level 2/3 混在時の verdict 分離

def test_warn_only_when_slow_and_no_ct_mismatch():
    result = make_result(status=200, elapsed_ms=4000.0, headers={"Content-Type": "application/json"})
    schema = make_schema(200, expected_content_type="application/json", expected_response_time_ms=3000.0)
    verdict, detail = verify(result, schema)
    assert verdict == WARN
    assert "応答時間超過" in detail
    assert "Content-Type" not in detail


def test_fail_only_when_ct_mismatch_and_no_slow():
    result = make_result(status=200, elapsed_ms=100.0, headers={"Content-Type": "text/html"})
    schema = make_schema(200, expected_content_type="application/json", expected_response_time_ms=3000.0)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "Content-Type" in detail
    assert "応答時間超過" not in detail


def test_fail_when_both_slow_and_ct_mismatch():
    result = make_result(status=200, elapsed_ms=4000.0, headers={"Content-Type": "text/html"})
    schema = make_schema(200, expected_content_type="application/json", expected_response_time_ms=3000.0)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "Content-Type" in detail
    assert "応答時間超過" not in detail


# Level 4: レスポンスボディの JSON Schema 適合

BODY_SCHEMA = {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}


def test_level4_pass_when_body_matches_schema():
    result = make_result(status=200, body='{"id": 1}')
    schema = make_schema(200, expected_body_schema=BODY_SCHEMA)
    verdict, detail = verify(result, schema)
    assert verdict == PASS


def test_level4_fail_when_body_missing_required_field():
    result = make_result(status=200, body="{}")
    schema = make_schema(200, expected_body_schema=BODY_SCHEMA)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "ボディ不適合" in detail


def test_level4_skipped_when_no_expected_body_schema():
    result = make_result(status=200, body="not json at all")
    schema = make_schema(200, expected_body_schema=None)
    verdict, _ = verify(result, schema)
    assert verdict == PASS


def test_level4_fail_takes_priority_over_warn():
    result = make_result(status=200, elapsed_ms=4000.0, body="{}")
    schema = make_schema(200, expected_response_time_ms=3000.0, expected_body_schema=BODY_SCHEMA)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "ボディ不適合" in detail


# Level 1 takes priority over Level 2/3

def test_level1_fail_overrides_slow_response():
    result = make_result(status=500, elapsed_ms=5000.0)
    schema = make_schema(200, expected_response_time_ms=3000.0)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "ステータス不一致" in detail
