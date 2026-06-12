import type { ResolvedSchema, TestCase } from '../../types.js'
import type { GeneratorContext } from '../index.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

type Context = GeneratorContext & { isRootBody: boolean }

export function generateObjectCases(schema: ResolvedSchema, ctx: Context): PartialCase[] {
  const cases: PartialCase[] = []

  if (!ctx.opts.includeAbnormal) return cases

  // additionalProperties: false — 未定義プロパティ追加（異常）
  if (schema.additionalProperties === false) {
    cases.push({
      summary: `${ctx.paramName} 未定義プロパティ追加（異常）`,
      keyword: 'additionalProperties',
      perspective: '異常系_additionalProperties',
      inputValue: '{ ...validBody, "__extra__": "value" }',
      expectedStatus: '400',
      expectedResult: 'バリデーションエラーが返ること',
      notes: 'スキーマ外のキーを含む JSON',
    })
  }

  // 空 body（required プロパティが 1 件以上ある場合のみ）
  if (ctx.isRootBody && schema.required && schema.required.length > 0) {
    cases.push({
      summary: `${ctx.paramName} 空 body（異常）`,
      keyword: 'required',
      perspective: '異常系_空body',
      inputValue: '{}',
      expectedStatus: '400',
      expectedResult: 'バリデーションエラーが返ること',
      notes: 'required プロパティが存在するため空 body は不正',
    })
  }

  return cases
}
