import SwaggerParser from '@apidevtools/swagger-parser'
import type { OpenAPI, OpenAPIV3, OpenAPIV3_1 } from 'openapi-types'
import { logger } from '../logger.js'

export type ParsedOpenAPI = OpenAPIV3.Document | OpenAPIV3_1.Document

export async function parseOpenAPI(inputPath: string): Promise<ParsedOpenAPI> {
  let api: OpenAPI.Document

  try {
    api = await SwaggerParser.dereference(inputPath)
  } catch (err) {
    throw new Error(`openapi.json の解析に失敗しました: ${(err as Error).message}`)
  }

  const version: string = (api as { openapi?: string }).openapi ?? ''
  if (!version.startsWith('3.')) {
    throw new Error(
      `OpenAPI 3.x のみ対応しています（検出バージョン: ${version || '不明'}）`
    )
  }

  logger.info({ version }, 'OpenAPI パース完了')

  normalizeExclusiveKeywords(api as ParsedOpenAPI)

  return api as ParsedOpenAPI
}

/**
 * OAS 3.0 の exclusiveMinimum/Maximum (boolean) を 3.1 スタイルの数値に正規化する。
 * 3.1 では exclusiveMinimum/Maximum が数値型なので、そのまま通す。
 * 正規化後は _exclusiveMinimumValue / _exclusiveMaximumValue に格納。
 */
function normalizeExclusiveKeywords(api: ParsedOpenAPI): void {
  walkSchemas(api, (schema: Record<string, unknown>) => {
    const exMin = schema.exclusiveMinimum
    const exMax = schema.exclusiveMaximum

    if (typeof exMin === 'boolean') {
      if (exMin === true && typeof schema.minimum === 'number') {
        schema._exclusiveMinimumValue = schema.minimum
      }
      delete schema.exclusiveMinimum
    } else if (typeof exMin === 'number') {
      schema._exclusiveMinimumValue = exMin
      delete schema.exclusiveMinimum
    }

    if (typeof exMax === 'boolean') {
      if (exMax === true && typeof schema.maximum === 'number') {
        schema._exclusiveMaximumValue = schema.maximum
      }
      delete schema.exclusiveMaximum
    } else if (typeof exMax === 'number') {
      schema._exclusiveMaximumValue = exMax
      delete schema.exclusiveMaximum
    }
  })
}

function walkSchemas(
  obj: unknown,
  visitor: (schema: Record<string, unknown>) => void,
  visited = new Set<unknown>()
): void {
  if (obj === null || typeof obj !== 'object') return
  if (visited.has(obj)) return
  visited.add(obj)

  const record = obj as Record<string, unknown>

  if (isSchemaObject(record)) {
    visitor(record)
  }

  for (const value of Object.values(record)) {
    walkSchemas(value, visitor, visited)
  }
}

function isSchemaObject(obj: Record<string, unknown>): boolean {
  return (
    'type' in obj ||
    'properties' in obj ||
    'items' in obj ||
    'allOf' in obj ||
    'anyOf' in obj ||
    'oneOf' in obj
  )
}
