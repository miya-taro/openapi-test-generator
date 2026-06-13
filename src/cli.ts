#!/usr/bin/env node
import { Command } from 'commander'
import { resolve } from 'node:path'
import { existsSync } from 'node:fs'
import { setLogLevel, logger } from './logger.js'
import { parseOpenAPI } from './parser/index.js'
import { extractSpecs, extractAuthSpecs } from './extractor/index.js'
import { generateTestCases } from './generator/index.js'
import { assignIds } from './id-assigner/index.js'
import { buildOutput, writeOutput } from './renderer/json.js'
import { writeExcelOutput } from './renderer/excel.js'
import type { GenerateOptions } from './types.js'

const program = new Command()

program
  .name('openapi-test-gen')
  .description('OpenAPI 3.x からインターフェース観点テスト仕様 JSON を自動生成します')
  .version('0.1.0')
  .argument('<input>', 'openapi.json のファイルパス')
  .option('-o, --output <path>', '出力ファイルパス', './test_cases.json')
  .option('--operations <ops>', '対象 operationId をカンマ区切りで指定')
  .option('--exclude-ops <ops>', '除外する operationId をカンマ区切りで指定')
  .option('--no-normal', '正常系ケースを生成しない')
  .option('--no-abnormal', '異常系ケースを生成しない')
  .option('--enum-full-coverage', 'enum の全値を正常ケースとして生成', false)
  .option('--log-level <level>', 'ログレベル (debug/info/warn/error)', 'info')
  .option('--dry-run', 'ケース数のみ表示し、ファイルを出力しない', false)
  .option('--fail-if-exists', '出力先ファイルが存在する場合はエラー終了', false)
  .option('--excel-output <path>', 'Excel (.xlsx) ファイルも出力する場合にパスを指定')
  .action(async (input: string, options: {
    output: string
    operations?: string
    excludeOps?: string
    normal: boolean
    abnormal: boolean
    enumFullCoverage: boolean
    logLevel: string
    dryRun: boolean
    failIfExists: boolean
    excelOutput?: string
  }) => {
    setLogLevel(options.logLevel)

    const inputPath = resolve(input)
    if (!existsSync(inputPath)) {
      logger.error({ path: inputPath }, '入力ファイルが見つかりません')
      process.exit(1)
    }

    const outputPath = resolve(options.output)
    if (options.failIfExists && existsSync(outputPath)) {
      logger.error({ path: outputPath }, '出力先ファイルがすでに存在します (--fail-if-exists)')
      process.exit(3)
    }

    const filterOps = options.operations
      ? new Set(options.operations.split(',').map(s => s.trim()))
      : null

    const excludeOps = options.excludeOps
      ? new Set(options.excludeOps.split(',').map(s => s.trim()))
      : null

    const genOpts: GenerateOptions = {
      includeNormal: options.normal,
      includeAbnormal: options.abnormal,
      enumFullCoverage: options.enumFullCoverage,
    }

    try {
      // Phase 1: Parse
      logger.info({ input: inputPath }, 'Phase 1: パース開始')
      const api = await parseOpenAPI(inputPath)

      // Phase 2: Extract
      logger.info('Phase 2: 抽出開始')
      let { paramSpecs, bodySpecs } = extractSpecs(api)

      let authSpecs = extractAuthSpecs(api)

      // フィルタリング
      if (filterOps) {
        paramSpecs = paramSpecs.filter(s => filterOps.has(s.operationId))
        bodySpecs = bodySpecs.filter(s => filterOps.has(s.operationId))
        authSpecs = authSpecs.filter(s => filterOps.has(s.operationId))
      }
      if (excludeOps) {
        paramSpecs = paramSpecs.filter(s => !excludeOps.has(s.operationId))
        bodySpecs = bodySpecs.filter(s => !excludeOps.has(s.operationId))
        authSpecs = authSpecs.filter(s => !excludeOps.has(s.operationId))
      }

      logger.info(
        { params: paramSpecs.length, bodyFields: bodySpecs.length, authOps: authSpecs.length },
        'Phase 2: 抽出完了'
      )

      // Phase 3: Generate
      logger.info('Phase 3: ケース生成開始')
      const rawCases = generateTestCases(paramSpecs, bodySpecs, genOpts, authSpecs)
      logger.info({ count: rawCases.length }, 'Phase 3: ケース生成完了')

      // Phase 4: ID Assign
      logger.info('Phase 4: ID 採番開始')
      const cases = assignIds(rawCases)

      // dry-run
      if (options.dryRun) {
        const normal = cases.filter(c => c.perspective.startsWith('正常系')).length
        const abnormal = cases.filter(c => c.perspective.startsWith('異常系')).length
        console.log(`生成ケース数: ${cases.length} 件（正常系: ${normal} 件、異常系: ${abnormal} 件）`)
        return
      }

      // Phase 5: Render
      logger.info('Phase 5: JSON 出力開始')
      const output = buildOutput(cases, inputPath)
      await writeOutput(output, outputPath)
      logger.info({ output: outputPath, total: cases.length }, '出力完了')
      console.log(`✓ ${cases.length} 件のテストケースを ${outputPath} に出力しました`)

      // Excel 出力（オプション）
      if (options.excelOutput) {
        const excelPath = resolve(options.excelOutput)
        logger.info({ output: excelPath }, 'Excel 出力開始')
        await writeExcelOutput(output, excelPath)
        logger.info({ output: excelPath }, 'Excel 出力完了')
        console.log(`✓ Excel を ${excelPath} に出力しました`)
      }
    } catch (err) {
      const message = (err as Error).message
      if (message.includes('OpenAPI 3.x のみ対応') || message.includes('解析に失敗')) {
        logger.error({ error: message }, '入力ファイルエラー')
        process.exit(1)
      }
      if (message.includes('$ref')) {
        logger.warn({ error: message }, '$ref 解決エラー')
        process.exit(2)
      }
      logger.error({ error: message }, '出力エラー')
      process.exit(3)
    }
  })

program.parseAsync(process.argv)
