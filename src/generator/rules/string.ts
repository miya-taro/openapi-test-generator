import type { ResolvedSchema, TestCase } from '../../types.js'
import type { GeneratorContext as Context } from '../index.js'
import { FORMAT_VALID_SAMPLES, FORMAT_INVALID_SAMPLES } from '../../samples/format-samples.js'
import { logger } from '../../logger.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

export function generateStringCases(schema: ResolvedSchema, ctx: Context): PartialCase[] {
  const cases: PartialCase[] = []

  // enum
  if (schema.enum && schema.enum.length > 0) {
    const enumValues = schema.enum as string[]

    if (ctx.opts.includeNormal) {
      if (ctx.opts.enumFullCoverage) {
        for (const val of enumValues) {
          cases.push({
            summary: `${ctx.paramName} enum 値 "${val}"（正常）`,
            keyword: 'enum',
            perspective: '正常系_enum値',
            inputValue: String(val),
            expectedStatus: ctx.successStatus,
            expectedResult: '正常に処理されること',
            notes: '',
          })
        }
      } else {
        cases.push({
          summary: `${ctx.paramName} enum 代表値（正常）`,
          keyword: 'enum',
          perspective: '正常系_enum代表値',
          inputValue: String(enumValues[0]),
          expectedStatus: ctx.successStatus,
          expectedResult: '正常に処理されること',
          notes: '',
        })
      }
    }

    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} enum 外の値（異常）`,
        keyword: 'enum',
        perspective: '異常系_enum外値',
        inputValue: '__INVALID__',
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // maxLength
  if (schema.maxLength !== undefined) {
    const maxLen = schema.maxLength
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最大長（正常）`,
        keyword: 'maxLength',
        perspective: '正常系_最大長',
        inputValue: 'a'.repeat(maxLen),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} 最大長+1（異常）`,
        keyword: 'maxLength',
        perspective: '異常系_最大長超過',
        inputValue: 'a'.repeat(maxLen + 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // minLength
  if (schema.minLength !== undefined) {
    const minLen = schema.minLength

    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最小長（正常）`,
        keyword: 'minLength',
        perspective: '正常系_最小長',
        inputValue: 'a'.repeat(minLen),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }

    // minLength = 0 の場合は異常系なし
    if (minLen > 0 && ctx.opts.includeAbnormal) {
      const invalidLen = minLen > 1 ? minLen - 1 : 0
      cases.push({
        summary: `${ctx.paramName} 最小長-1（異常）`,
        keyword: 'minLength',
        perspective: '異常系_最小長未満',
        inputValue: invalidLen === 0 ? '（空文字）' : 'a'.repeat(invalidLen),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // pattern
  if (schema.pattern) {
    const pattern = schema.pattern
    const validValue = reverseGeneratePattern(pattern)

    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} パターン一致（正常）`,
        keyword: 'pattern',
        perspective: '正常系_patternマッチ',
        inputValue: validValue ?? '[手動入力]',
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: validValue === null ? `正規表現: ${pattern}` : '',
      })
    }

    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} パターン不一致（異常）`,
        keyword: 'pattern',
        perspective: '異常系_patternミスマッチ',
        inputValue: '__BAD_PATTERN__',
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // format
  if (schema.format && schema.format !== 'binary') {
    const fmt = schema.format
    const validSample = FORMAT_VALID_SAMPLES[fmt]
    const invalidSample = FORMAT_INVALID_SAMPLES[fmt]

    if (validSample && ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} format:${fmt} 適合値（正常）`,
        keyword: 'format',
        perspective: `正常系_format_${fmt}`,
        inputValue: validSample,
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }

    if (invalidSample && ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} format:${fmt} 不適合値（異常）`,
        keyword: 'format',
        perspective: `異常系_format_${fmt}`,
        inputValue: invalidSample,
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: 'サーバが format をバリデートしない場合 200 の可能性あり',
      })
    }
  }

  return cases
}

function reverseGeneratePattern(pattern: string): string | null {
  try {
    // 動的 import を避けるため、シンプルなパターンのみ静的に対応
    // 複雑なパターンは null を返して [手動入力] にフォールバック
    const simple = trySimplePatternGeneration(pattern)
    if (simple !== null) return simple

    // randexp による逆生成を試みる
    const { default: RandExp } = require('randexp') as { default: new (pattern: string) => { gen(): string } }
    const re = new RandExp(pattern)
    const result = re.gen()
    // 生成結果が実際にパターンにマッチするか確認
    if (new RegExp(pattern).test(result)) return result
    return null
  } catch {
    logger.info({ pattern }, 'pattern 逆生成失敗 → [手動入力]')
    return null
  }
}

function trySimplePatternGeneration(pattern: string): string | null {
  // ^[0-9]{N}$ 形式
  const digitMatch = pattern.match(/^\^?\[0-9\]\{(\d+)\}\$?$/)
  if (digitMatch) {
    return '1'.repeat(Number(digitMatch[1]))
  }

  // ^[a-zA-Z]{N}$ 形式
  const alphaMatch = pattern.match(/^\^?\[a-zA-Z\]\{(\d+)\}\$?$/)
  if (alphaMatch) {
    return 'a'.repeat(Number(alphaMatch[1]))
  }

  // ^[a-z0-9]{N,M}$ 形式
  const alnumMatch = pattern.match(/^\^?\[a-z0-9\]\{(\d+),(\d+)\}\$?$/)
  if (alnumMatch) {
    return 'a'.repeat(Number(alnumMatch[1]))
  }

  return null
}
