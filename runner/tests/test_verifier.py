import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from verifier import verify, PASS, FAIL, WARN
from models import EXIT_ERROR, EXIT_OK, EXIT_TIMEOUT, RunCase, RunResult, ResponseSchema


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
    exit_code: int = EXIT_OK,
    error: str | None = None,
    body: str = "",
) -> RunResult:
    return RunResult(
        case=make_case(),
        actual_status=status,
        actual_body=body,
        actual_headers=headers or {},
        elapsed_ms=elapsed_ms,
        exit_code=exit_code,
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


def test_level1_fail_on_timeout():
    result = make_result(exit_code=EXIT_TIMEOUT, error="timeout")
    verdict, detail = verify(result, make_schema(200))
    assert verdict == FAIL
    assert "タイムアウト" in detail


def test_level1_fail_on_request_error():
    result = make_result(exit_code=EXIT_ERROR, error="connection refused")
    verdict, detail = verify(result, make_schema(200))
    assert verdict == FAIL
    assert "リクエストエラー" in detail


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


def test_level3_fail_content_type_with_shared_prefix_is_not_a_false_pass():
    # 回帰テスト: 以前は単純な前方一致だったため、期待値と文字列として前方一致する
    # 別のメディアタイプ（application/json-patch+json 等）を誤ってOK判定していた。
    result = make_result(status=200, headers={"Content-Type": "application/json-patch+json"})
    schema = make_schema(200, expected_content_type="application/json")
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "Content-Type" in detail


def test_level3_pass_content_type_case_insensitive():
    result = make_result(status=200, headers={"Content-Type": "Application/JSON; charset=UTF-8"})
    schema = make_schema(200, expected_content_type="application/json")
    verdict, detail = verify(result, schema)
    assert verdict == PASS


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


def test_security_fails_when_php_error_details_are_exposed():
    result = make_result(
        body="Warning: Undefined variable $user in /var/www/app.php on line 23"
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert "PHPエラー情報の露出" in detail
    assert "/var/www/app.php" not in detail


def test_security_detects_php_uncaught_database_exception():
    result = make_result(body="Uncaught PDOException: SQLSTATE[HY000] in /srv/api.php on line 8")

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert "PHPエラー情報の露出" in detail


def test_security_detects_exposed_sqlstate_without_echoing_database_details():
    result = make_result(
        body='{"error":"SQLSTATE[42S02]: Base table or view not found: 1146 users"}'
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert "データベースエラー情報の露出" in detail
    assert "Base table" not in detail
    assert "42S02" not in detail


@pytest.mark.parametrize("body", [
    "You have an error in your SQL syntax near 'OR 1=1'",
    'syntax error at or near "SELECT"',
    "Unterminated quoted string at or near input",
    "no such table: users_private",
    "Unknown column 'secret_column' in field list",
])
def test_security_detects_common_database_error_fingerprints_without_echoing(body):
    verdict, detail = verify(make_result(body=body), make_schema(200))

    assert verdict == FAIL
    assert "データベースエラー情報の露出" in detail
    assert body not in detail


def test_security_detects_private_key_block_without_echoing_key_material():
    result = make_result(
        body="-----BEGIN PRIVATE KEY-----\nprivate-key-material\n-----END PRIVATE KEY-----"
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert "秘密鍵ブロックの露出" in detail
    assert "private-key-material" not in detail


def test_security_does_not_flag_public_certificate_pem():
    result = make_result(
        body="-----BEGIN CERTIFICATE-----\npublic-certificate\n-----END CERTIFICATE-----"
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == PASS
    assert detail == ""


_SLACK_TEST_TOKEN = "xoxb-" + "123456789012-" + "abcdefghijklmnop"


@pytest.mark.parametrize(
    ("credential", "finding"),
    [
        ("ghp_123456789012345678901234567890123456", "GitHub形式のトークン"),
        ("github_pat_123456789012345678901234567890", "GitHub形式のトークン"),
        (_SLACK_TEST_TOKEN, "Slack形式のトークン"),
        ("AKIAIOSFODNN7EXAMPLE", "AWSアクセスキーID"),
        ("sk_live_12345678901234567890", "Stripe形式のAPIキー"),
    ],
)
def test_security_detects_known_provider_credentials_without_echoing_value(credential, finding):
    result = make_result(body=f'{{"diagnostic":"{credential}"}}')

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert finding in detail
    assert credential not in detail


def test_security_does_not_flag_short_credential_lookalikes_or_normal_jwt():
    result = make_result(
        body=(
            '{"message":"ghp_short xoxb-not-a-token sk_live_demo",'
            '"access_token":"eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"}'
        )
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == PASS
    assert detail == ""


def test_sensitive_header_mismatch_does_not_echo_header_value():
    secret_cookie = "sessionid=private-cookie-value"
    result = make_result(headers={"Set-Cookie": secret_cookie})

    verdict, detail = verify(
        result,
        make_schema(200, expected_headers={"Set-Cookie": "different-cookie"}),
    )

    assert verdict == FAIL
    assert "Set-Cookie不一致" in detail
    assert secret_cookie not in detail
    assert "private-cookie-value" not in detail


def test_security_fails_when_python_traceback_is_exposed_even_for_expected_error_status():
    result = make_result(
        status=500,
        body='Traceback (most recent call last):\n  File "app.py", line 12, in handler\nRuntimeError',
    )

    verdict, detail = verify(result, make_schema(500))

    assert verdict == FAIL
    assert "スタックトレースの露出" in detail


def test_status_failure_also_reports_stack_trace_without_response_contents():
    result = make_result(
        status=500,
        body='Traceback (most recent call last):\n  File "app.py", line 12\nRuntimeError',
    )

    verdict, detail = verify(result, make_schema(200))

    assert verdict == FAIL
    assert "ステータス不一致" in detail
    assert "スタックトレースの露出" in detail
    assert 'File "app.py"' not in detail


def test_security_does_not_flag_ordinary_warning_text():
    result = make_result(body="This warning is part of the product documentation.")

    verdict, detail = verify(result, make_schema(200))

    assert verdict == PASS
    assert detail == ""


# Level 1 takes priority over Level 2/3

def test_level1_fail_overrides_slow_response():
    result = make_result(status=500, elapsed_ms=5000.0)
    schema = make_schema(200, expected_response_time_ms=3000.0)
    verdict, detail = verify(result, schema)
    assert verdict == FAIL
    assert "ステータス不一致" in detail
