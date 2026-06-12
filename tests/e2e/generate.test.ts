import { describe, it, expect } from 'vitest'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseOpenAPI } from '../../src/parser/index.js'
import { extractSpecs } from '../../src/extractor/index.js'
import { generateTestCases } from '../../src/generator/index.js'
import { assignIds } from '../../src/id-assigner/index.js'
import type { GenerateOptions } from '../../src/types.js'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const FIXTURE = resolve(__dirname, 'fixtures/simple.openapi.json')

const ALL_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: false }

describe('E2E: simple.openapi.json', () => {
  it('パース・抽出・生成・採番が正常終了する', async () => {
    const api = await parseOpenAPI(FIXTURE)
    const { paramSpecs, bodySpecs } = extractSpecs(api)
    const rawCases = generateTestCases(paramSpecs, bodySpecs, ALL_OPTS)
    const cases = assignIds(rawCases)

    expect(cases.length).toBeGreaterThan(0)
    expect(cases.every(c => c.id.startsWith('TC-'))).toBe(true)
  })

  it('getUser の id パラメータに minimum/maximum ケースが含まれる', async () => {
    const api = await parseOpenAPI(FIXTURE)
    const { paramSpecs, bodySpecs } = extractSpecs(api)
    const rawCases = generateTestCases(paramSpecs, bodySpecs, ALL_OPTS)
    const cases = assignIds(rawCases)

    const getUserCases = cases.filter(c => c.operationId === 'getUser' && c.paramName === 'id')
    expect(getUserCases.some(c => c.keyword === 'minimum')).toBe(true)
    expect(getUserCases.some(c => c.keyword === 'maximum')).toBe(true)
  })

  it('getUser の status パラメータに enum ケースが含まれる', async () => {
    const api = await parseOpenAPI(FIXTURE)
    const { paramSpecs, bodySpecs } = extractSpecs(api)
    const rawCases = generateTestCases(paramSpecs, bodySpecs, ALL_OPTS)
    const cases = assignIds(rawCases)

    const statusCases = cases.filter(c => c.operationId === 'getUser' && c.paramName === 'status')
    expect(statusCases.some(c => c.keyword === 'enum')).toBe(true)
  })

  it('createUser に空 body 異常ケースが含まれる', async () => {
    const api = await parseOpenAPI(FIXTURE)
    const { paramSpecs, bodySpecs } = extractSpecs(api)
    const rawCases = generateTestCases(paramSpecs, bodySpecs, ALL_OPTS)
    const cases = assignIds(rawCases)

    const emptyCases = cases.filter(
      c => c.operationId === 'createUser' && c.perspective === '異常系_空body'
    )
    expect(emptyCases).toHaveLength(1)
  })

  it('全テストケースの ID が一意', async () => {
    const api = await parseOpenAPI(FIXTURE)
    const { paramSpecs, bodySpecs } = extractSpecs(api)
    const rawCases = generateTestCases(paramSpecs, bodySpecs, ALL_OPTS)
    const cases = assignIds(rawCases)

    const ids = cases.map(c => c.id)
    const uniqueIds = new Set(ids)
    expect(uniqueIds.size).toBe(ids.length)
  })
})
