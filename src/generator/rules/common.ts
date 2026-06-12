import type { ResolvedSchema, TestCase } from '../../types.js'
import type { GeneratorContext as Context } from '../index.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

export function generateCommonCases(
  schema: ResolvedSchema,
  required: boolean,
  ctx: Context
): PartialCase[] {
  const cases: PartialCase[] = []

  // required: false — 省略可能パラメータ省略時の正常系
  if (!required && ctx.opts.includeNormal) {
    cases.push({
      summary: `${ctx.paramName} 省略（正常）`,
      keyword: 'optional',
      perspective: '正常系_省略',
      inputValue: '（省略）',
      expectedStatus: ctx.successStatus,
      expectedResult: '正常に処理されること',
      notes: '',
    })
  }

  // required: true — 必須欠落（異常）
  if (required && ctx.opts.includeAbnormal) {
    const isPath = ctx.paramIn === 'path'
    cases.push({
      summary: `${ctx.paramName} 必須フィールド欠落（異常）`,
      keyword: 'required',
      perspective: '異常系_必須欠落',
      inputValue: '（フィールドを省略）',
      expectedStatus: isPath ? '404' : '400',
      expectedResult: isPath
        ? 'ルーティング失敗によりリソースが見つからないこと'
        : 'バリデーションエラーが返ること',
      notes: isPath ? 'ルーティング失敗により 404 の可能性あり' : '',
    })
  }

  // type — 型不正（異常）
  if (schema.type && ctx.opts.includeAbnormal) {
    const invalidValue = getInvalidValueForType(schema.type as string)
    if (invalidValue !== null) {
      const isPath = ctx.paramIn === 'path'
      cases.push({
        summary: `${ctx.paramName} 型不正値（異常）`,
        keyword: 'type',
        perspective: '異常系_型不正',
        inputValue: invalidValue,
        expectedStatus: '400',
        expectedResult: '型エラーが返ること',
        notes: isPath ? 'ルーティング失敗により 404 になる場合あり（実装依存）' : '',
      })
    }
  }

  return cases
}

function getInvalidValueForType(type: string): string | null {
  switch (type) {
    case 'integer':
    case 'number':
      return '"abc"'
    case 'boolean':
      return '"yes"'
    case 'array':
      return '"not-an-array"'
    case 'object':
      return '"not-an-object"'
    default:
      return null
  }
}
