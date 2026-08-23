import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_scenario_report import write_report, HEADERS


def test_write_report_creates_file_with_headers(tmp_path):
    output = tmp_path / "report.xlsx"
    write_report([("シナリオA", True, "201", "")], output)
    assert output.exists()

    wb = openpyxl.load_workbook(str(output))
    ws = wb.active
    header_values = [c.value for c in ws[2]]
    assert header_values == HEADERS


def test_write_report_row_values_match_input(tmp_path):
    output = tmp_path / "report.xlsx"
    write_report(
        [
            ("createUser", True, "201", ""),
            ("deleteUser", False, "404", "該当する行が見つかりません"),
        ],
        output,
    )
    wb = openpyxl.load_workbook(str(output))
    ws = wb.active
    row1 = [c.value for c in ws[3]]
    row2 = [c.value for c in ws[4]]
    assert row1[:4] == [1, "createUser", "OK", "201"]
    assert not row1[4]  # openpyxlは空文字を書き込むとNoneとして読み戻す
    assert row2 == [2, "deleteUser", "NG", "404", "該当する行が見つかりません"]


def test_write_report_ok_and_ng_rows_have_different_fill_colors(tmp_path):
    output = tmp_path / "report.xlsx"
    write_report([("ok_case", True, "200", ""), ("ng_case", False, "500", "err")], output)
    wb = openpyxl.load_workbook(str(output))
    ws = wb.active
    ok_fill = ws[3][0].fill.fgColor.rgb
    ng_fill = ws[4][0].fill.fgColor.rgb
    assert ok_fill != ng_fill


def test_write_report_empty_rows_still_creates_valid_file(tmp_path):
    output = tmp_path / "report.xlsx"
    write_report([], output)
    wb = openpyxl.load_workbook(str(output))
    ws = wb.active
    assert [c.value for c in ws[2]] == HEADERS
    assert ws.max_row == 2


def test_write_report_creates_parent_directory(tmp_path):
    output = tmp_path / "nested" / "dir" / "report.xlsx"
    write_report([("a", True, "200", "")], output)
    assert output.exists()
