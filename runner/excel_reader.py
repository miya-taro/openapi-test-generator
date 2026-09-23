from __future__ import annotations
from pathlib import Path
import openpyxl
from models import RunCase

COLUMN_MAP = {
    "試験ID": "id",
    "operationId": "operation_id",
    "パス": "path",
    "メソッド": "method",
    "in": "param_in",
    "パラメータ名": "param_name",
    "入力/操作": "input_value",
    "期待ステータス": "expected_status",
    "期待レスポンスボディ": "expected_response_body",
    "期待レスポンスヘッダ": "expected_response_header",
    "期待応答時間": "expected_response_time",
    "期待結果": "expected_result",
}


def read_excel(path: str | Path) -> list[RunCase]:
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb["test_spec"]

    rows = list(ws.iter_rows(values_only=True))
    # Header row is row 4 (index 3)
    header_row = rows[3]
    col_index: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        if cell is not None and str(cell) in COLUMN_MAP:
            col_index[COLUMN_MAP[str(cell)]] = i

    id_col = col_index.get("id")

    cases: list[RunCase] = []
    for row in rows[4:]:
        # 空行判定は「試験ID」列（ヘッダから見つけた実際の位置）で行う。row[0] 決め打ちだと、
        # 生成直後は必ず先頭列だが、ユーザーが手動で列を追加/並び替えた場合に空行判定を
        # 誤る（他の全フィールドと同じくヘッダ駆動の位置で見るのが一貫している）。
        if id_col is None or row[id_col] is None:
            continue
        def get(key: str, _row=row) -> str:
            idx = col_index.get(key)
            if idx is None:
                return ""
            v = _row[idx]
            return "" if v is None else str(v)

        cases.append(RunCase(
            id=get("id"),
            operation_id=get("operation_id"),
            path=get("path"),
            method=get("method"),
            param_in=get("param_in"),
            param_name=get("param_name"),
            input_value=get("input_value"),
            expected_status=get("expected_status"),
            expected_response_body=get("expected_response_body"),
            expected_response_header=get("expected_response_header"),
            expected_response_time=get("expected_response_time"),
            expected_result=get("expected_result"),
        ))

    wb.close()
    return cases
