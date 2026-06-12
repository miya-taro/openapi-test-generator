"""Run once to create tests/fixtures/sample.xlsx for tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import openpyxl
from openpyxl.styles import Font

def make_sample():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "test_spec"

    # Rows 1-3: title/meta (can be empty for test purposes)
    ws.append([None])
    ws.append([None])
    ws.append([None])

    # Row 4: headers
    headers = [
        "No", "operationId", "パス", "メソッド",
        "パラメータ区分", "パラメータ名", "入力値",
        "観点", "perspective", "概要", "備考",
        "期待ステータス", "期待レスポンスボディ", "期待レスポンスヘッダ", "期待応答時間", "期待結果",
    ]
    ws.append(headers)

    # Row 5+: data rows
    data = [
        ["TC-001-001", "getUsers", "/users", "GET",
         "query", "page", "1",
         "正常系", "正常系_最小値", "page 最小値（正常）", "",
         "200", "OpenAPI定義のJSON schemaに従うこと", "Content-Type: application/json", "3秒以内", "正常に処理されること"],
        ["TC-001-002", "getUsers", "/users", "GET",
         "query", "page", "0",
         "異常系", "異常系_最小値未満", "page 最小値未満（異常）", "",
         "400", "", "", "3秒以内", "バリデーションエラーが返ること"],
        ["TC-002-001", "createUser", "/users", "POST",
         "body", "name", "test",
         "正常系", "正常系_最小長", "name 最小長（正常）", "",
         "201", "OpenAPI定義のJSON schemaに従うこと", "Content-Type: application/json", "3秒以内", "正常に処理されること"],
    ]
    for row in data:
        ws.append(row)

    out = Path(__file__).parent / "fixtures" / "sample.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    print(f"Created {out}")

if __name__ == "__main__":
    make_sample()
