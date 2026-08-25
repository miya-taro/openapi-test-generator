import openpyxl

from src.renderer.excel_output import (
    write_excel_output,
    _build_curl_command,
    _encode_uri_component,
    COLUMNS,
    COLOR,
)
from src.renderer.json_output import build_output


def _tc(**overrides) -> dict:
    base = {
        "id": "TC-op-001",
        "operationId": "op",
        "summary": "summary",
        "path": "/users/{id}",
        "method": "GET",
        "in": "path",
        "paramName": "id",
        "keyword": "minimum",
        "perspective": "正常系_最小値",
        "inputValue": "1",
        "expectedStatus": "200",
        "expectedResponseBody": "",
        "expectedResponseHeader": "",
        "expectedResponseTime": "3秒以内",
        "expectedResult": "正常に処理されること",
        "verdict": "",
        "notes": "",
    }
    base.update(overrides)
    return base


# --- _encode_uri_component ---


def test_encode_uri_component_leaves_unreserved_chars():
    assert _encode_uri_component("abc-_.!~*'()123") == "abc-_.!~*'()123"


def test_encode_uri_component_escapes_special_chars():
    assert _encode_uri_component("a b/c") == "a%20b%2Fc"


# --- _build_curl_command ---


def test_curl_command_path_param_substituted():
    cmd = _build_curl_command(_tc(inputValue="42"))
    assert '"{BASE_URL}/users/42"' in cmd
    assert "GET" in cmd


def test_curl_command_omit_marker_keeps_placeholder():
    cmd = _build_curl_command(_tc(inputValue="（省略）"))
    assert "{id}" in cmd


def test_curl_command_query_param_appended():
    cmd = _build_curl_command(_tc(**{"in": "query"}, path="/users", paramName="page", inputValue="2"))
    assert "?page=2" in cmd


def test_curl_command_header_param():
    cmd = _build_curl_command(
        _tc(**{"in": "header"}, paramName="X-Api-Key", inputValue="secret")
    )
    assert '-H "X-Api-Key: secret"' in cmd


def test_curl_command_header_omit_no_header_flag():
    cmd = _build_curl_command(_tc(**{"in": "header"}, paramName="X-Api-Key", inputValue="（認証ヘッダなし）"))
    assert "-H" not in cmd


def test_curl_command_body_param_produces_json_payload():
    cmd = _build_curl_command(
        _tc(**{"in": "body"}, method="POST", path="/users", paramName="name", inputValue='"Alice"')
    )
    assert "Content-Type: application/json" in cmd
    # JSON中の " は cmd.exe/curl.exe への引数として安全に渡すため \" にエスケープされる
    assert '{\\"name\\": \\"Alice\\"}' in cmd


def test_curl_command_body_non_json_value_falls_back_to_raw_string():
    cmd = _build_curl_command(
        _tc(**{"in": "body"}, method="POST", path="/users", paramName="name", inputValue="not-an-int")
    )
    assert '{\\"name\\": \\"not-an-int\\"}' in cmd


def test_curl_command_header_value_with_quote_does_not_break_out():
    # ダブルクォートを含む値が -H の引数から脱出してコマンドを注入できないこと
    cmd = _build_curl_command(
        _tc(**{"in": "header"}, paramName="X-Api-Key", inputValue='secret" & calc.exe & "')
    )
    assert '-H "X-Api-Key: secret\\" & calc.exe & \\""' in cmd


def test_curl_command_body_value_with_quote_does_not_break_out():
    # openapi.json 由来の値にクォートやシェルメタ文字が含まれても -d の引数を脱出できないこと
    cmd = _build_curl_command(
        _tc(
            **{"in": "body"},
            method="POST",
            path="/users",
            paramName="name",
            inputValue="O'Brien'; touch pwned #",
        )
    )
    assert "-d \"" in cmd
    # 生成されたコマンド全体が対応の取れた引用符で構成されていること（脱出していない）
    assert cmd.count('"') % 2 == 0


def test_curl_command_empty_marker_sends_empty_string():
    cmd = _build_curl_command(
        _tc(**{"in": "query"}, path="/users", paramName="q", inputValue="（空文字）")
    )
    assert "?q=" in cmd


# --- write_excel_output ---


def test_write_excel_output_creates_sheet_with_expected_headers(tmp_path):
    output = build_output([_tc()], "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    wb = openpyxl.load_workbook(str(out_path))
    assert wb.sheetnames == ["test_spec"]
    ws = wb["test_spec"]
    header_row = [c.value for c in ws[4]]
    assert header_row == [col[0] for col in COLUMNS]


def test_write_excel_output_data_row_values(tmp_path):
    output = build_output([_tc(summary="サマリー")], "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    ws = openpyxl.load_workbook(str(out_path))["test_spec"]
    row = [c.value for c in ws[5]]
    assert row[0] == "TC-op-001"
    assert row[2] == "サマリー"
    assert row[-1].startswith("curl.exe")  # curl コマンド列


def test_write_excel_output_normal_and_abnormal_row_colors(tmp_path):
    cases = [
        _tc(id="TC-op-001", perspective="正常系_最小値"),
        _tc(id="TC-op-002", perspective="異常系_必須欠落"),
    ]
    output = build_output(cases, "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    ws = openpyxl.load_workbook(str(out_path))["test_spec"]
    normal_fill = ws.cell(row=5, column=1).fill.fgColor.rgb
    abnormal_fill = ws.cell(row=6, column=1).fill.fgColor.rgb
    assert normal_fill == COLOR["normalBg"]
    assert abnormal_fill == COLOR["abnormalBg"]


def test_write_excel_output_verdict_dropdown_added_when_cases_exist(tmp_path):
    output = build_output([_tc()], "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    ws = openpyxl.load_workbook(str(out_path))["test_spec"]
    dvs = ws.data_validations.dataValidation
    assert len(dvs) == 1
    assert "OK" in dvs[0].formula1


def test_write_excel_output_no_dropdown_when_no_cases(tmp_path):
    output = build_output([], "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    ws = openpyxl.load_workbook(str(out_path))["test_spec"]
    assert len(ws.data_validations.dataValidation) == 0


def test_write_excel_output_freeze_panes_and_meta_rows(tmp_path):
    output = build_output([_tc()], "openapi.json")
    out_path = tmp_path / "out.xlsx"
    write_excel_output(output, str(out_path))

    ws = openpyxl.load_workbook(str(out_path))["test_spec"]
    assert ws.freeze_panes == "A5"
    assert ws.cell(row=1, column=1).value == "Source"
    assert ws.cell(row=2, column=2).value == output["meta"]["totalCases"]
