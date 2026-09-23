from workflow.html_report import write_html_report, write_failed_case_ids
from workflow.case_master import write_case_master


def test_html_report_links_results_by_case_id_and_marks_unapproved_cases(tmp_path):
    master_path = tmp_path / "case-master.json"
    write_case_master({
        "format": "api-tester.case-master",
        "schemaVersion": 1,
        "project": {"name": "<Orders>"},
        "cases": [
            {"caseId": "TC-1", "kind": "contract", "title": "<script>bad()</script>",
             "source": {}, "definition": {}, "expected": {}, "reviewStatus": "draft"},
            {"caseId": "DB-2", "kind": "db-scenario", "title": "DB item",
             "source": {}, "definition": {}, "expected": {}, "reviewStatus": "approved"},
        ],
    }, master_path)
    contract = tmp_path / "contract.xml"
    contract.write_text('''<testsuites><testsuite tests="1" failures="1" errors="0">
      <testcase name="TC-1"><failure message="secret detail">do-not-render</failure></testcase>
    </testsuite></testsuites>''', encoding="utf-8")
    db = tmp_path / "db.xml"
    db.write_text('''<testsuites><testsuite tests="1" failures="0" errors="0">
      <testcase name="DB-2" scenarioName="DB item" />
    </testsuite></testsuites>''', encoding="utf-8")
    output = tmp_path / "report.html"

    write_html_report(master_path, [contract, db], output)

    html = output.read_text(encoding="utf-8")
    assert "TC-1" in html and "DB-2" in html
    assert "NG" in html and "OK" in html
    assert "未承認" in html
    assert "approved" in html
    assert "&lt;script&gt;bad()&lt;/script&gt;" in html
    assert "do-not-render" not in html
    assert "secret detail" not in html


def test_html_report_marks_cases_without_execution_as_not_run(tmp_path):
    master_path = tmp_path / "case-master.json"
    write_case_master({
        "format": "api-tester.case-master", "schemaVersion": 1,
        "project": {"name": "sample"},
        "cases": [{"caseId": "TC-1", "kind": "contract", "title": "Not run",
                   "source": {}, "definition": {}, "expected": {}, "reviewStatus": "reviewed"}],
    }, master_path)
    output = tmp_path / "report.html"

    write_html_report(master_path, [], output)

    assert "未実行" in output.read_text(encoding="utf-8")


def test_unapproved_case_in_an_unexecuted_layer_does_not_mark_report_as_exploratory(tmp_path):
    master_path = tmp_path / "case-master.json"
    write_case_master({
        "format": "api-tester.case-master", "schemaVersion": 1,
        "project": {"name": "sample"},
        "cases": [
            {"caseId": "TC-1", "kind": "contract", "title": "Approved contract",
             "source": {}, "definition": {}, "expected": {}, "reviewStatus": "approved"},
            {"caseId": "DB-1", "kind": "db-scenario", "title": "Unrun draft DB scenario",
             "source": {}, "definition": {}, "expected": {}, "reviewStatus": "draft"},
        ],
    }, master_path)
    junit = tmp_path / "contract.xml"
    junit.write_text('<testsuites><testsuite><testcase name="TC-1"/></testsuite></testsuites>', encoding="utf-8")
    output = tmp_path / "report.html"

    write_html_report(master_path, [junit], output)

    report = output.read_text(encoding="utf-8")
    assert "承認済み試験仕様" in report
    assert "探索実行（未承認" not in report


def test_failed_case_list_contains_only_failure_and_error_case_ids(tmp_path):
    junit = tmp_path / "result.xml"
    junit.write_text('''<testsuites><testsuite>
      <testcase name="TC-fail"><failure message="ng"/></testcase>
      <testcase name="TC-error"><error message="timeout"/></testcase>
      <testcase name="TC-warn"><system-out>warn</system-out></testcase>
      <testcase name="TC-ok"/>
    </testsuite></testsuites>''', encoding="utf-8")
    output = tmp_path / "failed.json"

    write_failed_case_ids([junit], output)

    assert output.read_text(encoding="utf-8")
    import json
    assert json.loads(output.read_text(encoding="utf-8")) == ["TC-fail", "TC-error"]
