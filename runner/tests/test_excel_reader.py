import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent.parent))
from excel_reader import read_excel
from models import RunCase

FIXTURE = Path(__file__).parent / "fixtures" / "sample.xlsx"


def test_read_returns_list_of_run_cases():
    cases = read_excel(FIXTURE)
    assert len(cases) == 3
    assert all(isinstance(c, RunCase) for c in cases)


def test_first_case_fields():
    cases = read_excel(FIXTURE)
    c = cases[0]
    assert c.id == "TC-001-001"
    assert c.operation_id == "getUsers"
    assert c.path == "/users"
    assert c.method == "GET"
    assert c.param_in == "query"
    assert c.param_name == "page"
    assert c.input_value == "1"
    assert c.expected_status == "200"
    assert c.expected_response_body == "OpenAPI定義のJSON schemaに従うこと"
    assert c.expected_response_time == "3秒以内"


def test_missing_optional_field_defaults_to_empty_string():
    cases = read_excel(FIXTURE)
    # TC-001-002 has empty expected_response_body and header
    c = cases[1]
    assert c.expected_response_body == ""
    assert c.expected_response_header == ""


def test_third_case_is_post():
    cases = read_excel(FIXTURE)
    c = cases[2]
    assert c.method == "POST"
    assert c.param_in == "body"
    assert c.expected_status == "201"


def _build_workbook(tmp_path, headers: list[str], rows: list[list]) -> Path:
    """test_spec シート・row4ヘッダーという実際の生成物と同じ構造の最小ワークブックを作る。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "test_spec"
    for _ in range(3):  # ヘッダーは4行目（index 3）
        ws.append([])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    path = tmp_path / "spec.xlsx"
    wb.save(str(path))
    return path


def test_blank_row_detection_with_extra_leading_column(tmp_path):
    # 「試験ID」の前に別の列が挿入されていても、試験ID列を見て正しく判定できること
    path = _build_workbook(
        tmp_path,
        headers=["メモ", "試験ID", "operationId"],
        rows=[
            [None, "TC-001", "getUsers"],   # メモ列は空だが試験IDはある → 読み込まれるべき
            ["備考あり", None, None],        # 試験ID自体が空 → スキップされるべき
        ],
    )
    cases = read_excel(path)
    assert len(cases) == 1
    assert cases[0].id == "TC-001"
    assert cases[0].operation_id == "getUsers"
