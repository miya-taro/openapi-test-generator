import ExcelJS from 'exceljs'
import type { TestCase } from '../types.js'
import type { OutputJson } from './json.js'

// ── 列定義 ─────────────────────────────────────────────────────────
const COLUMNS: { header: string; key: keyof TestCase; width: number }[] = [
  { header: '試験ID',         key: 'id',             width: 18 },
  { header: 'operationId',   key: 'operationId',    width: 20 },
  { header: '概要',           key: 'summary',        width: 36 },
  { header: 'パス',           key: 'path',           width: 22 },
  { header: 'メソッド',       key: 'method',         width: 10 },
  { header: 'in',            key: 'in',             width: 12 },
  { header: 'パラメータ名',   key: 'paramName',      width: 20 },
  { header: 'Keyword',       key: 'keyword',        width: 20 },
  { header: '観点',           key: 'perspective',    width: 24 },
  { header: '入力/操作',      key: 'inputValue',     width: 30 },
  { header: '期待ステータス',       key: 'expectedStatus',       width: 14 },
  { header: '期待レスポンスボディ', key: 'expectedResponseBody',   width: 36 },
  { header: '期待レスポンスヘッダ', key: 'expectedResponseHeader', width: 30 },
  { header: '期待応答時間',         key: 'expectedResponseTime',   width: 14 },
  { header: '期待結果',             key: 'expectedResult',         width: 30 },
  { header: '判定',           key: 'verdict',        width: 10 },
  { header: '備考',           key: 'notes',          width: 36 },
]

// ── 色定数 ─────────────────────────────────────────────────────────
const COLOR = {
  headerBg:    'FF1F3864',  // ヘッダ行：濃紺 (#1F3864)
  headerFg:    'FFFFFFFF',
  metaBg:      'FFE8EDF4',  // meta行：薄い青グレー
  metaLabel:   'FF555555',
  normalBg:    'FFE2EFDA',  // 正常系行：薄緑
  abnormalBg:  'FFFCE4D6',  // 異常系行：薄オレンジ
  verdictBg:   'FFFFF2CC',  // 判定列：薄黄
  border:      'FFAAAAAA',
}

function applyBorder(cell: ExcelJS.Cell) {
  const side: ExcelJS.BorderStyle = 'thin'
  cell.border = {
    top:    { style: side, color: { argb: COLOR.border } },
    left:   { style: side, color: { argb: COLOR.border } },
    bottom: { style: side, color: { argb: COLOR.border } },
    right:  { style: side, color: { argb: COLOR.border } },
  }
}

// ── META 行を書き込む（行 1〜2）─────────────────────────────────────
function writeMetaRows(sheet: ExcelJS.Worksheet, meta: OutputJson['meta'], colCount: number) {
  // 行1: source / generatedAt
  const row1 = sheet.getRow(1)
  row1.getCell(1).value = 'Source'
  row1.getCell(2).value = meta.source
  row1.getCell(4).value = 'Generated At'
  row1.getCell(5).value = meta.generatedAt

  // 行2: totalCases / normalCases / abnormalCases
  const row2 = sheet.getRow(2)
  row2.getCell(1).value = 'Total Cases'
  row2.getCell(2).value = meta.totalCases
  row2.getCell(4).value = 'Normal'
  row2.getCell(5).value = meta.normalCases
  row2.getCell(7).value = 'Abnormal'
  row2.getCell(8).value = meta.abnormalCases

  for (const row of [row1, row2]) {
    for (let c = 1; c <= colCount; c++) {
      const cell = row.getCell(c)
      cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLOR.metaBg } }
      cell.font = { color: { argb: COLOR.metaLabel }, size: 10 }
    }
    // ラベルセルを太字に
    for (const ci of [1, 4, 7]) {
      const cell = row.getCell(ci)
      cell.font = { bold: true, color: { argb: COLOR.metaLabel }, size: 10 }
    }
    row.height = 16
  }

  // meta行を列結合（source, generatedAt の値欄を2列分）
  sheet.mergeCells(1, 2, 1, 3)
  sheet.mergeCells(1, 5, 1, 6)
  sheet.mergeCells(2, 2, 2, 3)
  sheet.mergeCells(2, 5, 2, 6)
}

// ── 注意書き行を書き込む（行 3）─────────────────────────────────────
function writeNoteRow(sheet: ExcelJS.Worksheet, colCount: number) {
  const noteRow = sheet.getRow(3)
  const noteCell = noteRow.getCell(1)
  noteCell.value = '※ 本シートはインターフェース観点のテストケースです。Layer2以降のシナリオテストは別シートを参照してください。'
  noteCell.font = { italic: true, color: { argb: 'FF555555' }, size: 9 }
  noteCell.alignment = { vertical: 'middle' }
  noteRow.height = 16
  sheet.mergeCells(3, 1, 3, colCount)
}

// ── ヘッダ行を書き込む（行 4）────────────────────────────────────────
function writeHeaderRow(sheet: ExcelJS.Worksheet) {
  const headerRow = sheet.getRow(4)
  COLUMNS.forEach((col, i) => {
    const cell = headerRow.getCell(i + 1)
    cell.value = col.header
    cell.fill  = { type: 'pattern', pattern: 'solid', fgColor: { argb: COLOR.headerBg } }
    cell.font  = { bold: true, color: { argb: COLOR.headerFg }, size: 10 }
    cell.alignment = { vertical: 'middle', horizontal: 'center' }
    applyBorder(cell)
  })
  headerRow.height = 20
}

// ── データ行を書き込む（行 5 〜）────────────────────────────────────
function writeDataRows(
  sheet: ExcelJS.Worksheet,
  cases: TestCase[],
  verdictColIdx: number,
) {
  const verdictValues = ['OK', 'NG', '未実施']

  cases.forEach((tc, rowIdx) => {
    const rowNum = rowIdx + 5  // 1=meta1, 2=meta2, 3=note, 4=header
    const isNormal = tc.perspective.startsWith('正常系')
    const rowBg = isNormal ? COLOR.normalBg : COLOR.abnormalBg

    const row = sheet.getRow(rowNum)
    COLUMNS.forEach((col, colIdx) => {
      const cell = row.getCell(colIdx + 1)
      cell.value = tc[col.key] as string ?? ''
      cell.font = { size: 10 }
      cell.alignment = { vertical: 'top', wrapText: true }
      applyBorder(cell)

      const isVerdict = colIdx + 1 === verdictColIdx
      cell.fill = {
        type: 'pattern',
        pattern: 'solid',
        fgColor: { argb: isVerdict ? COLOR.verdictBg : rowBg },
      }
    })

    // 判定列にドロップダウンを設定
    const verdictCell = row.getCell(verdictColIdx)
    verdictCell.dataValidation = {
      type: 'list',
      allowBlank: true,
      formulae: [`"${verdictValues.join(',')}"`],
      error: '選択肢から選んでください',
      errorTitle: '入力エラー',
      prompt: 'OK / NG / 未実施 から選択',
    }

    row.height = 32
  })
}

// ── シート列幅・行固定を設定 ─────────────────────────────────────────
function configureSheet(sheet: ExcelJS.Worksheet) {
  COLUMNS.forEach((col, i) => {
    sheet.getColumn(i + 1).width = col.width
  })
  // 行1〜4（meta×2 + 注意書き + ヘッダ）を固定
  sheet.views = [{ state: 'frozen', xSplit: 0, ySplit: 4 }]
  // 印刷設定
  sheet.pageSetup = {
    orientation: 'landscape',
    fitToPage: true,
    fitToWidth: 1,
    fitToHeight: 0,
  }
}

// ── PUBLIC API ───────────────────────────────────────────────────────
export async function writeExcelOutput(output: OutputJson, excelPath: string): Promise<void> {
  const workbook = new ExcelJS.Workbook()
  workbook.creator = 'openapi-test-gen'
  workbook.created = new Date()

  const sheet = workbook.addWorksheet('test_spec', {
    properties: { defaultRowHeight: 15 },
  })

  const verdictColIdx = COLUMNS.findIndex(c => c.key === 'verdict') + 1

  writeMetaRows(sheet, output.meta, COLUMNS.length)
  writeNoteRow(sheet, COLUMNS.length)
  writeHeaderRow(sheet)
  writeDataRows(sheet, output.cases, verdictColIdx)
  configureSheet(sheet)

  await workbook.xlsx.writeFile(excelPath)
}
