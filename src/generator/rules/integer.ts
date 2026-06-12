import type { ResolvedSchema, TestCase } from '../../types.js'
import type { GeneratorContext as Context } from '../index.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

export function generateIntegerCases(schema: ResolvedSchema, ctx: Context): PartialCase[] {
  const cases: PartialCase[] = []
  const isNumber = schema.type === 'number'
  const step = isNumber ? 0.1 : 1

  const min = schema.minimum
  const max = schema.maximum
  const exMinVal = schema._exclusiveMinimumValue
  const exMaxVal = schema._exclusiveMaximumValue

  // minimum
  if (min !== undefined) {
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最小値（正常）`,
        keyword: 'minimum',
        perspective: '正常系_最小値',
        inputValue: String(min),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} 最小値未満（異常）`,
        keyword: 'minimum',
        perspective: '異常系_最小値未満',
        inputValue: String(isNumber ? min - step : min - 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: isNumber ? '小数点以下を考慮' : '',
      })
    }
  }

  // maximum
  if (max !== undefined) {
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最大値（正常）`,
        keyword: 'maximum',
        perspective: '正常系_最大値',
        inputValue: String(max),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} 最大値超過（異常）`,
        keyword: 'maximum',
        perspective: '異常系_最大値超過',
        inputValue: String(isNumber ? max + step : max + 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // 中間値（minimum + maximum の両方がある場合）
  if (min !== undefined && max !== undefined && ctx.opts.includeNormal) {
    const mid = Math.floor((min + max) / 2)
    cases.push({
      summary: `${ctx.paramName} 中間値（正常）`,
      keyword: 'minimum+maximum',
      perspective: '正常系_中間値',
      inputValue: String(mid),
      expectedStatus: ctx.successStatus,
      expectedResult: '正常に処理されること',
      notes: '',
    })
  }

  // exclusiveMinimum
  if (exMinVal !== undefined) {
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} exclusiveMinimum 境界値そのもの（異常）`,
        keyword: 'exclusiveMinimum',
        perspective: '異常系_exclusiveMinimum境界値',
        inputValue: String(exMinVal),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} exclusiveMinimum 境界値+1（正常）`,
        keyword: 'exclusiveMinimum',
        perspective: '正常系_exclusiveMinimum超過値',
        inputValue: String(isNumber ? exMinVal + step : exMinVal + 1),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
  }

  // exclusiveMaximum
  if (exMaxVal !== undefined) {
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} exclusiveMaximum 境界値そのもの（異常）`,
        keyword: 'exclusiveMaximum',
        perspective: '異常系_exclusiveMaximum境界値',
        inputValue: String(exMaxVal),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} exclusiveMaximum 境界値-1（正常）`,
        keyword: 'exclusiveMaximum',
        perspective: '正常系_exclusiveMaximum未満値',
        inputValue: String(isNumber ? exMaxVal - step : exMaxVal - 1),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
  }

  // multipleOf
  if (schema.multipleOf !== undefined) {
    const m = schema.multipleOf
    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} multipleOf 倍数値（正常）`,
        keyword: 'multipleOf',
        perspective: '正常系_multipleOf倍数',
        inputValue: String(m * 2),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }
    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} multipleOf 非倍数値（異常）`,
        keyword: 'multipleOf',
        perspective: '異常系_multipleOf非倍数',
        inputValue: String(m + 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  return cases
}
