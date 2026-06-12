import type { OpenAPIV3, OpenAPIV3_1 } from 'openapi-types'
import type { ParsedOpenAPI } from '../parser/index.js'
import type { ParamSpec, BodyFieldSpec, ResolvedSchema, ResponseInfo } from '../types.js'
import { logger } from '../logger.js'

const STANDARD_HEADERS = new Set([
  'authorization',
  'content-type',
  'accept',
  'accept-encoding',
  'accept-language',
  'cache-control',
  'connection',
  'host',
  'user-agent',
])

export function extractSpecs(api: ParsedOpenAPI): {
  paramSpecs: ParamSpec[]
  bodySpecs: BodyFieldSpec[]
} {
  const paramSpecs: ParamSpec[] = []
  const bodySpecs: BodyFieldSpec[] = []

  const paths = api.paths ?? {}

  for (const [path, pathItem] of Object.entries(paths)) {
    if (!pathItem) continue

    const methods = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head'] as const

    for (const method of methods) {
      const operation = (pathItem as Record<string, unknown>)[method] as
        | OpenAPIV3.OperationObject
        | OpenAPIV3_1.OperationObject
        | undefined

      if (!operation) continue

      const operationId = resolveOperationId(operation, method, path)
      const successStatus = resolveSuccessStatus(operation.responses as Record<string, unknown> | undefined)
      const responsesInfo = buildResponsesInfo(operation.responses as Record<string, unknown> | undefined)

      // parameters
      const parameters = [
        ...((pathItem.parameters ?? []) as OpenAPIV3.ParameterObject[]),
        ...((operation.parameters ?? []) as OpenAPIV3.ParameterObject[]),
      ]

      for (const param of parameters) {
        if (!param.name || !param.in) continue

        const paramIn = param.in as ParamSpec['in']

        if (paramIn === 'header' && STANDARD_HEADERS.has(param.name.toLowerCase())) {
          logger.debug({ name: param.name }, '標準ヘッダをスキップ')
          continue
        }

        const schema = (param.schema ?? {}) as ResolvedSchema

        if (schema.format === 'binary') {
          logger.debug({ name: param.name }, 'binary フィールドをスキップ')
          continue
        }

        paramSpecs.push({
          operationId,
          path,
          method: method.toUpperCase(),
          in: paramIn,
          name: param.name,
          required: paramIn === 'path' ? true : (param.required ?? false),
          schema,
          successStatus,
          responsesInfo,
        })
      }

      // requestBody
      const requestBody = operation.requestBody as OpenAPIV3.RequestBodyObject | undefined
      if (requestBody) {
        const jsonContent = requestBody.content?.['application/json']
        if (!jsonContent) {
          logger.debug({ operationId }, 'application/json 以外の requestBody をスキップ')
          continue
        }

        const bodySchema = jsonContent.schema as ResolvedSchema | undefined
        if (!bodySchema) continue

        const fields = flattenBodySchema(bodySchema, '', operationId, path, method.toUpperCase(), successStatus, responsesInfo)
        bodySpecs.push(...fields)
      }
    }
  }

  return { paramSpecs, bodySpecs }
}

function resolveSuccessStatus(responses: Record<string, unknown> | undefined): string {
  if (!responses) return '200'
  const successCodes = Object.keys(responses).filter(code => /^2\d\d$/.test(code)).sort()
  return successCodes[0] ?? '200'
}

function buildResponsesInfo(responses: Record<string, unknown> | undefined): Record<string, ResponseInfo> {
  if (!responses) return {}
  const result: Record<string, ResponseInfo> = {}
  for (const [status, response] of Object.entries(responses)) {
    const resp = response as { content?: Record<string, unknown>; headers?: Record<string, unknown> } | undefined
    if (!resp) continue
    result[status] = {
      contentTypes: resp.content ? Object.keys(resp.content) : [],
      headerNames: resp.headers ? Object.keys(resp.headers) : [],
    }
  }
  return result
}

function resolveOperationId(
  operation: OpenAPIV3.OperationObject | OpenAPIV3_1.OperationObject,
  method: string,
  path: string
): string {
  if (operation.operationId) return operation.operationId
  const normalized = path.replace(/\{([^}]+)\}/g, '$1').replace(/\//g, '_').replace(/^_/, '')
  return `${method.toUpperCase()}_${normalized}`
}

function flattenBodySchema(
  schema: ResolvedSchema,
  parentPath: string,
  operationId: string,
  path: string,
  method: string,
  successStatus: string,
  responsesInfo: Record<string, import('../types.js').ResponseInfo>
): BodyFieldSpec[] {
  const results: BodyFieldSpec[] = []

  if (schema.type === 'object' || schema.properties) {
    const requiredFields = new Set(schema.required ?? [])
    const properties = schema.properties ?? {}

    // オブジェクト自体のスペック（空body チェック等に使う）
    if (parentPath === '') {
      results.push({
        operationId,
        path,
        method,
        fieldPath: '__body__',
        required: true,
        schema,
        successStatus,
        responsesInfo,
      })
    }

    for (const [propName, propSchema] of Object.entries(properties)) {
      if (!propSchema) continue

      const fieldPath = parentPath ? `${parentPath}.${propName}` : propName
      const resolvedSchema = propSchema as ResolvedSchema

      if (resolvedSchema.format === 'binary') {
        logger.debug({ fieldPath }, 'binary フィールドをスキップ')
        continue
      }

      results.push({
        operationId,
        path,
        method,
        fieldPath,
        required: requiredFields.has(propName),
        schema: resolvedSchema,
        successStatus,
        responsesInfo,
      })

      // ネストされたオブジェクトを再帰的に展開
      if (resolvedSchema.type === 'object' || resolvedSchema.properties) {
        results.push(
          ...flattenBodySchema(resolvedSchema, fieldPath, operationId, path, method, successStatus, responsesInfo)
        )
      }
    }
  }

  return results
}
