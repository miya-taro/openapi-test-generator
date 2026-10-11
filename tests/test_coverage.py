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


def test_a_single_boundary_case_does_not_hide_missing_opposite_side():
    api = {"paths": {"/a": {"post": {"operationId": "a", "requestBody": {"required": True, "content": {
        "application/json": {"schema": {"type": "number", "minimum": 1}}
    }}}}}}
    cases = [{"id": "min", "operationId": "a", "in": "body", "paramName": "requestBody",
              "keyword": "minimum", "perspective": "正常系_最小値", "inputValue": "1"}]
    rows = build_coverage(api, cases)
    assert next(r for r in rows if r['keyword'] == 'minimum / 正常側')['caseIds'] == ['min']
    assert next(r for r in rows if r['keyword'] == 'minimum / 異常側')['status'] == '未生成'
    assert next(r for r in rows if r['keyword'] == 'body必須 / 欠落')['status'] == '未生成'
    assert next(r for r in rows if r['keyword'] == 'type / 不正型:boolean')['status'] == '未生成'


def test_impossible_integer_non_multiple_is_not_reported_as_missing():
    api = {"paths": {"/a": {"post": {"operationId": "a", "requestBody": {"content": {
        "application/json": {"schema": {"type": "integer", "multipleOf": 1}}
    }}}}}}
    rows = build_coverage(api, [])
    assert next(r for r in rows if r['keyword'] == 'multipleOf / 異常側')['status'] == '該当なし'
    assert next(r for r in rows if r['keyword'] == 'multipleOf / 正常側')['status'] == '未生成'


def test_enum_inventory_keeps_each_missing_value_visible():
    api = {"paths": {"/a": {"post": {"operationId": "a", "requestBody": {"content": {
        "application/json": {"schema": {"type": "integer", "enum": [1, 2, 3]}}
    }}}}}}
    cases = [{"id": "one", "operationId": "a", "in": "body", "paramName": "requestBody",
              "keyword": "enum", "perspective": "正常系_enum値", "inputValue": "__JSON_VALUE__1"}]
    rows = build_coverage(api, cases)
    assert next(r for r in rows if r['keyword'] == 'enum / 正常値:1')['caseIds'] == ['one']
    assert next(r for r in rows if r['keyword'] == 'enum / 正常値:2')['status'] == '未生成'
    assert next(r for r in rows if r['keyword'] == 'enum / 正常値:3')['status'] == '未生成'
    assert next(r for r in rows if r['keyword'] == 'enum / 同型の範囲外値')['status'] == '未生成'
