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

HEADERS = ["No", "シナリオ名", "判定", "APIステータス", "詳細"]

_HEADER_FILL = PatternFill(fill_type="solid", fgColor=COLOR["headerBg"])
_HEADER_FONT = Font(color=COLOR["headerFg"], bold=True)
_OK_FILL = PatternFill(fill_type="solid", fgColor=COLOR["normalBg"])
_NG_FILL = PatternFill(fill_type="solid", fgColor=COLOR["abnormalBg"])
_THIN_BORDER = Border(
    top=Side(style="thin", color=COLOR["border"]),
    left=Side(style="thin", color=COLOR["border"]),
    bottom=Side(style="thin", color=COLOR["border"]),
    right=Side(style="thin", color=COLOR["border"]),
)
_COL_WIDTHS = [6, 30, 8, 16, 60]


def write_report(rows: list[tuple[str, bool, str, str]], output_path: str | Path) -> None:
    """rows: [(シナリオ名, 適合したか, APIステータス表示用文字列, 詳細メッセージ), ...]"""
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

    for i, (name, ok, api_status, detail) in enumerate(rows, start=1):
        row = [i, name, "OK" if ok else "NG", api_status, detail]
        ws.append(row)
        for cell in ws[i + 2]:
            cell.fill = _OK_FILL if ok else _NG_FILL
            cell.border = _THIN_BORDER
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    for col_idx, width in enumerate(_COL_WIDTHS, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
