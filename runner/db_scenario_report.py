"""db_scenario_runner.py の実行結果をExcelレポートとして出力する。

Layer1（openapi-test-run）の結果Excelと違い、Layer2はこれまで標準出力の
ログしか残らなかった。QA記録・チーム内共有として持ち出せる成果物が無かったため、
シナリオ名・判定・APIステータス・詳細を一覧できるシートを新規に作る。
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.renderer.excel_output import COLOR
from request_evidence import write_request_sheet

HEADERS = ["No", "試験ID", "シナリオ名", "判定", "APIステータス", "詳細"]

_HEADER_FILL = PatternFill(fill_type="solid", fgColor=COLOR["headerBg"])
_HEADER_FONT = Font(color=COLOR["headerFg"], bold=True)
_OK_FILL = PatternFill(fill_type="solid", fgColor=COLOR["normalBg"])
_NG_FILL = PatternFill(fill_type="solid", fgColor=COLOR["abnormalBg"])
_WARNING_FILL = PatternFill(fill_type="solid", fgColor=COLOR["warningBg"] if "warningBg" in COLOR else "FFF2CC")
_THIN_BORDER = Border(
    top=Side(style="thin", color=COLOR["border"]),
    left=Side(style="thin", color=COLOR["border"]),
    bottom=Side(style="thin", color=COLOR["border"]),
    right=Side(style="thin", color=COLOR["border"]),
)
_COL_WIDTHS = [6, 22, 30, 8, 16, 60]


def write_report(rows: list[tuple], output_path: str | Path, evidence: list[dict] | None = None) -> None:
    """Accept legacy 4-field rows and case-ID-aware 5-field rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DBシナリオ結果"

    ws.append([f"実行日時: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"])
    ws.append(HEADERS)
    header_row = ws[2]
    for cell in header_row:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _THIN_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for i, row_data in enumerate(rows, start=1):
        if len(row_data) == 5:
            case_id, name, result, api_status, detail = row_data
        elif len(row_data) == 4:
            name, result, api_status, detail = row_data
            case_id = ""
        else:
            raise ValueError("DBシナリオ結果の行は4要素または5要素で指定してください")
        verdict = result if isinstance(result, str) else "OK" if result else "NG"
        row = [i, case_id, name, verdict, api_status, detail]
        ws.append(row)
        fill = _OK_FILL if verdict == "OK" else _WARNING_FILL if verdict == "未確認" else _NG_FILL
        for cell in ws[i + 2]:
            cell.fill = fill
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for col_idx, width in enumerate(_COL_WIDTHS, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    ws.freeze_panes = "A3"  # 実行日時行・ヘッダ行を固定し、シナリオ数が多くてもスクロール時に見失わないようにする

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if evidence is not None:
        write_request_sheet(wb, [{"case_id": row.get("case_id"), "verdict": row.get("verdict"),
                                 "status": row.get("api_status"), "request": row.get("sent_request", {})}
                                for row in evidence])
    wb.save(str(output_path))
