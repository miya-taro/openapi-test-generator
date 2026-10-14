from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import openpyxl
from models import RunResult
from request_evidence import readable_curl, write_request_sheet
from sensitive_data import redact_header_value, redact_sensitive_text
from report_layout import safe_cell, style_table, write_overview

RESULT_HEADERS = [
    "実行日時",        # P
    "実測ステータス",  # Q
    "実測ヘッダ",      # R
    "実測ボディ",      # S
    "応答時間(ms)",    # T
    "判定詳細",        # U
    "実行コマンド",    # V
]

BODY_MAX_LEN = 21


def write_results(
    source_path: str | Path,
    results: list[tuple[RunResult, str, str]],  # (result, verdict, detail)
    output_path: str | Path,
    full_body: bool = False,
) -> None:
    wb = openpyxl.load_workbook(str(source_path))
    ws = wb["test_spec"]

    header_row_idx = 4  # 1-based row index for headers

    # Find the first empty column after existing headers
    header_row = ws[header_row_idx]
    last_col = 0
    for cell in header_row:
        if cell.value is not None:
            last_col = cell.column
    start_col = last_col + 1 if last_col > 0 else 1

    # Write result column headers
    for i, h in enumerate(RESULT_HEADERS):
        ws.cell(row=header_row_idx, column=start_col + i, value=h)

    # Build id → row index map (data starts at row 5)
    id_col = _find_column(ws, header_row_idx, "試験ID")
    id_to_row: dict[str, int] = {}
    for row_idx in range(header_row_idx + 1, ws.max_row + 1):
        cell_val = ws.cell(row=row_idx, column=id_col).value
        if cell_val is not None:
            id_to_row[str(cell_val)] = row_idx

    preview_col = next((cell.column for cell in ws[header_row_idx] if cell.value in {"curl コマンド", "送信予定curl（Bash形式）", "送信curl（Bash形式）"}), None)
    if preview_col:
        ws.cell(row=header_row_idx, column=preview_col, value="送信curl（Bash形式）")
        for row_idx in range(header_row_idx + 1, ws.max_row + 1):
            ws.cell(row=row_idx, column=preview_col).value = "未実行"

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    verdict_col = next((cell.column for cell in ws[header_row_idx] if cell.value == "判定"), None)
    if verdict_col is None:
        verdict_col = start_col + len(RESULT_HEADERS)
        ws.cell(row=header_row_idx, column=verdict_col, value="判定")

    for result, verdict, detail in results:
        row_idx = id_to_row.get(result.case.id)
        if row_idx is None:
            continue
        ws.cell(row=row_idx, column=verdict_col, value=verdict)
        source_body = result.report_body if result.report_body is not None else result.actual_body
        safe_body = redact_sensitive_text(source_body)
        body_preview = safe_body if full_body else _truncate(safe_body, BODY_MAX_LEN)
        ws.cell(row=row_idx, column=start_col + 0, value=now)
        ws.cell(row=row_idx, column=start_col + 1, value=result.actual_status or "")
        ws.cell(row=row_idx, column=start_col + 2, value=_format_headers(result.actual_headers))
        ws.cell(row=row_idx, column=start_col + 3, value=body_preview)
        ws.cell(row=row_idx, column=start_col + 4, value=round(result.elapsed_ms, 1))
        ws.cell(row=row_idx, column=start_col + 5, value=safe_cell(detail))
        ws.cell(row=row_idx, column=start_col + 6, value=result.curl_command)
        if preview_col:
            ws.cell(row=row_idx, column=preview_col, value=readable_curl(result.request_evidence) or result.curl_command or "送信内容なし")

    write_request_sheet(wb, [
        {"case_id": result.case.id, "verdict": verdict, "status": result.actual_status,
         "request": result.request_evidence} for result, verdict, _ in results
    ], first=not any(s.title.startswith("試験仕様_") for s in wb.worksheets))
    by_id = {result.case.id: verdict for result, verdict, _ in results}
    readable_titles = {}
    for summary in wb.worksheets:
        if summary.title.startswith("試験仕様_"):
            for row in range(5, summary.max_row + 1):
                summary.cell(row, 7, by_id.get(str(summary.cell(row, 9).value), "未実施"))
                readable_titles[str(summary.cell(row, 9).value)] = summary.cell(row, 2).value
    # Keep the detailed source sheet stable; offer a compact landing page instead.
    result_by_id = {result.case.id: (result, verdict, detail) for result, verdict, detail in results}
    title_col = next((cell.column for cell in ws[4] if cell.value == '概要'), id_col)
    expected_col = next((cell.column for cell in ws[4] if cell.value == '期待ステータス'), None)
    if '実行詳細' in wb.sheetnames:
        del wb['実行詳細']
    details = wb.create_sheet('実行詳細')
    details.append(['実測値と送信内容。本文は実行設定に従い省略します。全文が必要なら実行前にfull-bodyを選択してください。長いセルは数式バーでも確認できます。'])
    details.append(['No.', '試験項目', '判定', '期待ステータス', '実測ステータス', '判定詳細', '実測ヘッダ', '実測ボディ', '送信curl（Bash形式）'])
    overview = []
    for number, (case_id, row_idx) in enumerate(id_to_row.items(), 1):
        item = result_by_id.get(case_id)
        result, verdict, detail = item if item else (None, '未実施', '今回の実行結果に記録がありません')
        title = readable_titles.get(case_id) or ws.cell(row_idx, title_col).value or case_id
        body = redact_sensitive_text(result.report_body if result.report_body is not None else result.actual_body) if result else ''
        expected = result.case.expected_status if result else (ws.cell(row_idx, expected_col).value if expected_col else None)
        details.append([safe_cell(value) for value in [number, title, verdict, expected,
                        result.actual_status or '応答なし' if result else '未実行', detail,
                        _format_headers(result.actual_headers) if result else '', body if full_body else _truncate(body, BODY_MAX_LEN),
                        readable_curl(result.request_evidence) or result.curl_command if result else '未実行']])
        overview.append({'number': number, 'title': title,
                         'verdict': verdict, 'expected': result.case.expected_status if result else (ws.cell(row_idx, expected_col).value if expected_col else None),
                         'actual': result.actual_status if result else None, 'elapsed': round(result.elapsed_ms, 1) if result else None,
                         'detail': detail, 'sheet': details.title, 'row': details.max_row})
    for offset, width in enumerate([26, 18, 45, 65, 18, 65, 90]):
        ws.column_dimensions[openpyxl.utils.get_column_letter(start_col + offset)].width = width
    style_table(ws, [ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width or 18 for i in range(1, ws.max_column + 1)], 4, verdict_col)
    style_table(details, [7, 42, 13, 20, 20, 65, 45, 65, 90], 2, 3)
    write_overview(wb, overview)
    wb.save(str(output_path))


def _find_column(ws, row_idx: int, header: str) -> int:
    for cell in ws[row_idx]:
        if cell.value == header:
            return cell.column
    return 1


def _truncate(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


def _format_headers(headers: dict[str, str]) -> str:
    return "\n".join(f"{k}: {redact_header_value(k, v)}" for k, v in headers.items())
