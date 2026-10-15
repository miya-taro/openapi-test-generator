"""Fixed pytest adapter: one reviewed case is one pytest item, including under xdist."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from execution_plan import load_plan
from runtime_service import RuntimeService


def _options():
    return json.loads(Path(os.environ["OTG_EXECUTION_OPTIONS"]).read_text(encoding="utf-8"))


def pytest_generate_tests(metafunc):
    if "api_case" in metafunc.fixturenames:
        options = _options()
        _, cases, _ = load_plan(options["master"], options["kind"], options["case_ids"])
        metafunc.parametrize("api_case", cases, ids=[case["caseId"] for case in cases])


def pytest_collection_modifyitems(items):
    for item in items:
        case = item.callspec.params["api_case"]
        item.name = case["caseId"]  # Stable IDs in native pytest JUnit and rerun lists.
        item._nodeid = item.nodeid.rsplit("::", 1)[0] + "::" + case["caseId"]


@pytest.fixture(scope="session")
def api_runtime():
    options = _options()
    _, cases, api = load_plan(options["master"], options["kind"], options["case_ids"])
    # All side effects are in the fixture: --collect-only never logs in or touches DB.
    with RuntimeService(api, cases, options) as runtime:
        yield runtime


def save_record(record):
    destination = Path(_options()["records"])
    name = hashlib.sha256(record["caseId"].encode("utf-8")).hexdigest()
    path = destination / (name + ".json")
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    if report.failed and (call.when != "call" or not getattr(item, "api_record_written", False)):
        case = item.callspec.params["api_case"]
        # Do not serialize exception messages/locals; they can contain passwords/SQL.
        save_record({"caseId": case["caseId"], "kind": case["kind"],
                     "definitionHash": case["definitionHash"], "status": "error", "verdict": "NG",
                     "detail": f"試験の{call.when}処理でエラーが発生しました。接続・認証・設定を確認してください",
                     "actualStatus": 0})
        report.longrepr = "試験の準備・実行・後片付けを完了できませんでした（機密情報保護のため例外本文は出力しません）"
