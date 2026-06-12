export type ParamIn = 'path' | 'query' | 'header' | 'cookie'

export interface ResponseInfo {
  contentTypes: string[]
  headerNames: string[]
}

export interface ResolvedSchema {
  type?: string | string[]
  format?: string
  enum?: unknown[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number | boolean
  exclusiveMaximum?: number | boolean
  multipleOf?: number
  minLength?: number
  maxLength?: number
  pattern?: string
  minItems?: number
  maxItems?: number
  uniqueItems?: boolean
  required?: string[]
  properties?: Record<string, ResolvedSchema>
  additionalProperties?: boolean | ResolvedSchema
  items?: ResolvedSchema
  nullable?: boolean
  // OAS 3.1 正規化後に使うフィールド
  _exclusiveMinimumValue?: number
  _exclusiveMaximumValue?: number
}

export interface ParamSpec {
  operationId: string
  path: string
  method: string
  in: ParamIn
  name: string
  required: boolean
  schema: ResolvedSchema
  successStatus: string
  responsesInfo: Record<string, ResponseInfo>
}

export interface BodyFieldSpec {
  operationId: string
  path: string
  method: string
  fieldPath: string
  required: boolean
  schema: ResolvedSchema
  successStatus: string
  responsesInfo: Record<string, ResponseInfo>
}

export type FieldSpec = ParamSpec | BodyFieldSpec

export interface TestCase {
  id: string
  operationId: string
  summary: string
  path: string
  method: string
  in: string
  paramName: string
  keyword: string
  perspective: string
  inputValue: string
  expectedStatus: string
  expectedResponseBody: string
  expectedResponseHeader: string
  expectedResponseTime: string
  expectedResult: string
  verdict: ''
  notes: string
}

export interface GenerateOptions {
  includeNormal: boolean
  includeAbnormal: boolean
  enumFullCoverage: boolean
  // TODO: --generate-minimal-request を追加予定。
  // 対象: requestBody が required:true かつ type:object かつ required 配列を持つ operation。
  // 生成ルール: required フィールドのみを代表値で埋めた最小 JSON を 1 ケース生成する（正常系_最小有効リクエスト）。
  // 実装タイミング: JSON/Excel/CLI/OpenAPI 3.0+3.1 対応の土台が安定してから後付けオプションとして追加。
}
