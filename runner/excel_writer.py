from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import openpyxl
from models import RunResult
from request_evidence import readable_curl, write_request_sheet
from sensitive_data import redact_header_value, redact_sensitive_text

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

    preview_col = next((cell.column for cell in ws[header_row_idx] if cell.value in {"curl コマンド", "送信curl（Bash形式）"}), None)
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
        ws.cell(row=row_idx, column=start_col + 5, value=detail)
        ws.cell(row=row_idx, column=start_col + 6, value=result.curl_command)
        if preview_col:
            ws.cell(row=row_idx, column=preview_col, value=readable_curl(result.request_evidence) or result.curl_command or "送信内容なし")

    write_request_sheet(wb, [
        {"case_id": result.case.id, "verdict": verdict, "status": result.actual_status,
         "request": result.request_evidence} for result, verdict, _ in results
    ], first=True)
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
