from src.coverage import build_coverage, write_coverage_sheet
from openpyxl import Workbook


def test_coverage_distinguishes_generation_from_unhandled_constraints():
    api = {"paths": {"/a": {"post": {"operationId": "a", "requestBody": {"content": {"application/json": {"schema": {
        "type": "object", "required": ["x"], "properties": {"x": {"type": "integer", "minimum": 2},
        "list": {"type": "array", "contains": {"const": 1}}},
    }}}}, "responses": {"200": {"content": {"application/json": {"schema": {"type": "string", "format": "custom-format"}}}}}}}}}
    cases = [{"id": "c1", "operationId": "a", "in": "body", "paramName": "x", "keyword": "minimum"}]
    rows = build_coverage(api, cases)
    assert next(r for r in rows if r["keyword"] == "minimum")["status"] == "ケース生成済み"
    assert next(r for r in rows if r["keyword"] == "required")["status"] == "未生成"
    assert next(r for r in rows if r["keyword"] == "contains")["status"] == "未対応"
    assert next(r for r in rows if r["keyword"] == "format")["status"] == "未対応"
    assert build_coverage(api, cases, selected={"other"}) == []
    wb = Workbook()
    write_coverage_sheet(wb, rows)
    assert wb["対応状況"].max_row == len(rows) + 1
