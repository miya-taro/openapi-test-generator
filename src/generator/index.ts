import type { ParamSpec, BodyFieldSpec, TestCase, GenerateOptions, ResolvedSchema, ResponseInfo } from '../types.js'
import { generateCommonCases } from './rules/common.js'
import { generateIntegerCases } from './rules/integer.js'
import { generateStringCases } from './rules/string.js'
import { generateArrayCases } from './rules/array.js'
import { generateObjectCases } from './rules/object.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

function deriveResponseBody(info: ResponseInfo | undefined): string {
  if (!info) return ''
  const { contentTypes } = info
  if (contentTypes.length === 0) return 'レスポンスボディなし'
  if (contentTypes.includes('application/json')) return 'OpenAPI定義のJSON schemaに従うこと'
  if (contentTypes.length === 1) return `${contentTypes[0]} に従うレスポンスを返すこと`
  return 'OpenAPIレスポンス定義を確認すること'
}

function deriveResponseHeader(info: ResponseInfo | undefined): string {
  if (!info) return ''
  const { contentTypes, headerNames } = info
  const lines: string[] = []
  if (contentTypes.length === 1) {
    lines.push(`Content-Type: ${contentTypes[0]}`)
  } else if (contentTypes.length > 1) {
    lines.push('Content-Type: （複数あり・要確認）')
  }
  for (const header of headerNames) {
    lines.push(`${header}: OpenAPI定義を確認`)
  }
  return lines.join('\n')
}

export interface GeneratorContext {
  paramIn: string
  paramName: string
  opts: GenerateOptions
  successStatus: string
}

// 現在の生成スコープ: Validation Keyword 単位のフィールド個別テスト（Layer 1）のみ。
// 以下は Layer 1 標準では扱わない:
//   - string フィールドへの型不正（実装依存で期待ステータスが安定しないため）
//   - Content-Type 不正 / integer への float / non-nullable への null（実装依存）
//   - 最小有効リクエスト（Layer 2 寄り）→ --generate-minimal-request として後付け予定（GenerateOptions 参照）
export function generateTestCases(
  paramSpecs: ParamSpec[],
  bodySpecs: BodyFieldSpec[],
  opts: GenerateOptions
): Omit<TestCase, 'id'>[] {
  const results: Omit<TestCase, 'id'>[] = []

  for (const spec of paramSpecs) {
    const partials = generateFromSchema(spec.schema, spec.required, spec.in, spec.name, opts, spec.successStatus)
    for (const partial of partials) {
      results.push({
        operationId: spec.operationId,
        path: spec.path,
        method: spec.method,
        in: spec.in,
        paramName: spec.name,
        verdict: '',
        ...partial,
        expectedResponseBody: deriveResponseBody(spec.responsesInfo[partial.expectedStatus]),
        expectedResponseHeader: deriveResponseHeader(spec.responsesInfo[partial.expectedStatus]),
        expectedResponseTime: '3秒以内',
      })
    }
  }

  for (const spec of bodySpecs) {
    const isRootBody = spec.fieldPath === '__body__'
    const paramIn = 'body'
    const paramName = isRootBody ? 'requestBody' : spec.fieldPath

    const partials = generateFromSchema(spec.schema, spec.required, paramIn, paramName, opts, spec.successStatus, isRootBody)
    for (const partial of partials) {
      results.push({
        operationId: spec.operationId,
        path: spec.path,
        method: spec.method,
        in: paramIn,
        paramName,
        verdict: '',
        ...partial,
        expectedResponseBody: deriveResponseBody(spec.responsesInfo[partial.expectedStatus]),
        expectedResponseHeader: deriveResponseHeader(spec.responsesInfo[partial.expectedStatus]),
        expectedResponseTime: '3秒以内',
      })
    }
  }

  return results
}

function generateFromSchema(
  schema: ResolvedSchema,
  required: boolean,
  paramIn: string,
  paramName: string,
  opts: GenerateOptions,
  successStatus: string,
  isRootBody = false
): PartialCase[] {
  const cases: PartialCase[] = []
  const ctx: GeneratorContext = { paramIn, paramName, opts, successStatus }

  // 共通ルール（required, type）
  cases.push(...generateCommonCases(schema, required, ctx))

  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type

  switch (type) {
    case 'integer':
    case 'number':
      cases.push(...generateIntegerCases(schema, ctx))
      break

    case 'string':
      cases.push(...generateStringCases(schema, ctx))
      break

    case 'array':
      cases.push(...generateArrayCases(schema, ctx))
      break

    case 'object':
      cases.push(...generateObjectCases(schema, { paramIn, paramName, opts, successStatus, isRootBody }))
      break

    default:
      // type 不明の場合でも format/enum がある string 系を試みる
      if (schema.enum || schema.format || schema.maxLength !== undefined || schema.minLength !== undefined || schema.pattern) {
        cases.push(...generateStringCases(schema, ctx))
      }
      break
  }

  return cases
}
