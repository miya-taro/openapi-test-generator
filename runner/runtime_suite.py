"""The only pytest test function used for application execution; no generated code."""
import pytest

from pytest_runtime import save_record


def test_api_case(api_case, api_runtime, request):
    record = api_runtime.run(api_case)
    save_record(record)
    request.node.api_record_written = True
    if record["status"] == "unverified":
        pytest.skip(record["detail"] or "判定に必要な条件を満たしていません")
    if record["status"] != "passed":
        pytest.fail(record["detail"] or "期待結果と一致しません", pytrace=False)
