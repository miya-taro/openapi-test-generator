import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from junit_writer import write_junit_xml, write_junit_xml_scenarios
from models import EXIT_OK, EXIT_TIMEOUT, RunCase, RunResult
from verifier import FAIL, PASS, WARN


def make_case(id_: str = "TC-001-001") -> RunCase:
    return RunCase(
        id=id_, operation_id="getUsers", path="/users", method="GET",
        param_in="query", param_name="page", input_value="1",
        expected_status="200", expected_response_body="",
        expected_response_header="", expected_response_time="3秒以内",
        expected_result="",
    )


def make_result(case: RunCase, exit_code: int = EXIT_OK, error: str | None = None) -> RunResult:
    return RunResult(
        case=case, actual_status=200, actual_body="{}", actual_headers={},
        elapsed_ms=123.0, exit_code=exit_code, curl_command="curl.exe -s ...", error=error,
    )


# --- write_junit_xml (Layer1) ---

def test_write_junit_xml_creates_valid_xml_with_correct_counts(tmp_path):
    case1, case2, case3 = make_case("TC-001"), make_case("TC-002"), make_case("TC-003")
    results = [
        (make_result(case1), PASS, ""),
        (make_result(case2), FAIL, "ステータス不一致"),
        (make_result(case3), WARN, "応答時間超過"),
    ]
    out = tmp_path / "result.xml"
    write_junit_xml(results, out)

    root = ET.parse(str(out)).getroot()
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "1"
    assert suite.get("errors") == "0"


def test_write_junit_xml_failure_case_has_failure_element(tmp_path):
    case = make_case()
    results = [(make_result(case), FAIL, "ステータス不一致: 期待=200, 実測=500")]
    out = tmp_path / "result.xml"
    write_junit_xml(results, out)

    root = ET.parse(str(out)).getroot()
    testcase = root.find(".//testcase")
    assert testcase.get("name") == "TC-001-001"
    assert testcase.get("classname") == "GET /users"
    failure = testcase.find("failure")
    assert failure is not None
    assert "ステータス不一致" in failure.get("message")


def test_write_junit_xml_pass_case_has_no_child_elements(tmp_path):
    case = make_case()
    results = [(make_result(case), PASS, "")]
    out = tmp_path / "result.xml"
    write_junit_xml(results, out)

    root = ET.parse(str(out)).getroot()
    testcase = root.find(".//testcase")
    assert list(testcase) == []


def test_write_junit_xml_warn_case_uses_system_out_not_failure(tmp_path):
    case = make_case()
    results = [(make_result(case), WARN, "応答時間超過: 4000ms > 3000ms")]
    out = tmp_path / "result.xml"
    write_junit_xml(results, out)

    root = ET.parse(str(out)).getroot()
    testcase = root.find(".//testcase")
    assert testcase.find("failure") is None
    assert testcase.find("error") is None
    system_out = testcase.find("system-out")
    assert system_out is not None
    assert "応答時間超過" in system_out.text
    # WARN は failures にカウントしない（runner.py 本体もWARNのみなら終了コード2でFAILの1とは区別している）
    suite = root.find("testsuite")
    assert suite.get("failures") == "0"


def test_write_junit_xml_transport_error_uses_error_element_not_failure(tmp_path):
    case = make_case()
    results = [(make_result(case, exit_code=EXIT_TIMEOUT, error="タイムアウトしました"), FAIL, "タイムアウト")]
    out = tmp_path / "result.xml"
    write_junit_xml(results, out)

    root = ET.parse(str(out)).getroot()
    testcase = root.find(".//testcase")
    assert testcase.find("failure") is None
    error_el = testcase.find("error")
    assert error_el is not None
    suite = root.find("testsuite")
    assert suite.get("errors") == "1"
    assert suite.get("failures") == "0"


def test_write_junit_xml_creates_parent_directory(tmp_path):
    out = tmp_path / "nested" / "dir" / "result.xml"
    write_junit_xml([(make_result(make_case()), PASS, "")], out)
    assert out.exists()


# --- write_junit_xml_scenarios (Layer2) ---

def test_write_junit_xml_scenarios_counts_and_structure(tmp_path):
    rows = [
        ("ユーザー作成", True, "201", ""),
        ("在庫が減る", False, "200", "stock: 期待=9 実測=10"),
    ]
    out = tmp_path / "scenarios.xml"
    write_junit_xml_scenarios(rows, out)

    root = ET.parse(str(out)).getroot()
    suite = root.find("testsuite")
    assert suite.get("tests") == "2"
    assert suite.get("failures") == "1"

    testcases = root.findall(".//testcase")
    assert testcases[0].get("name") == "ユーザー作成"
    assert testcases[0].find("failure") is None
    assert testcases[1].get("name") == "在庫が減る"
    failure = testcases[1].find("failure")
    assert failure is not None
    assert "stock" in failure.get("message")


def test_write_junit_xml_scenarios_empty_rows(tmp_path):
    out = tmp_path / "scenarios.xml"
    write_junit_xml_scenarios([], out)
    root = ET.parse(str(out)).getroot()
    suite = root.find("testsuite")
    assert suite.get("tests") == "0"
    assert suite.get("failures") == "0"


def test_write_junit_xml_scenarios_uses_shared_case_id(tmp_path):
    out = tmp_path / "scenarios.xml"
    write_junit_xml_scenarios(
        [("DB-create-user", "create user", False, "500", "failure detail")], out
    )

    testcase = ET.parse(out).getroot().find(".//testcase")
    assert testcase.get("name") == "DB-create-user"
    assert testcase.get("scenarioName") == "create user"
    assert testcase.find("failure") is not None
