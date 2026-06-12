import type { ResolvedSchema, TestCase } from '../../types.js'
import type { GeneratorContext as Context } from '../index.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

export function generateArrayCases(schema: ResolvedSchema, ctx: Context): PartialCase[] {
  const cases: PartialCase[] = []

  const itemType = schema.items?.type ?? 'string'
  const sampleItem = getSampleItem(itemType)

  // minItems
  if (schema.minItems !== undefined) {
    const minItems = schema.minItems

    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最小要素数（正常）`,
        keyword: 'minItems',
        perspective: '正常系_minItems',
        inputValue: buildArrayValue(sampleItem, minItems),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }

    if (ctx.opts.includeAbnormal && minItems > 0) {
      cases.push({
        summary: `${ctx.paramName} 最小要素数-1（異常）`,
        keyword: 'minItems',
        perspective: '異常系_minItems未満',
        inputValue: buildArrayValue(sampleItem, minItems - 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // maxItems
  if (schema.maxItems !== undefined) {
    const maxItems = schema.maxItems

    if (ctx.opts.includeNormal) {
      cases.push({
        summary: `${ctx.paramName} 最大要素数（正常）`,
        keyword: 'maxItems',
        perspective: '正常系_maxItems',
        inputValue: buildArrayValue(sampleItem, maxItems),
        expectedStatus: ctx.successStatus,
        expectedResult: '正常に処理されること',
        notes: '',
      })
    }

    if (ctx.opts.includeAbnormal) {
      cases.push({
        summary: `${ctx.paramName} 最大要素数+1（異常）`,
        keyword: 'maxItems',
        perspective: '異常系_maxItems超過',
        inputValue: buildArrayValue(sampleItem, maxItems + 1),
        expectedStatus: '400',
        expectedResult: 'バリデーションエラーが返ること',
        notes: '',
      })
    }
  }

  // uniqueItems
  if (schema.uniqueItems === true && ctx.opts.includeAbnormal) {
    cases.push({
      summary: `${ctx.paramName} 重複要素あり（異常）`,
      keyword: 'uniqueItems',
      perspective: '異常系_uniqueItems重複',
      inputValue: `[${sampleItem}, ${sampleItem}]`,
      expectedStatus: '400',
      expectedResult: 'バリデーションエラーが返ること',
      notes: '',
    })
  }

  return cases
}

function getSampleItem(itemType: string): string {
  switch (itemType) {
    case 'integer':
    case 'number':
      return '1'
    case 'boolean':
      return 'true'
    default:
      return '"a"'
  }
}

function buildArrayValue(item: string, count: number): string {
  if (count === 0) return '[]'
  return `[${Array(count).fill(item).join(', ')}]`
}
