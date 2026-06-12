import { describe, it, expect } from 'vitest'
import { generateCommonCases } from '../../src/generator/rules/common.js'
import type { GenerateOptions } from '../../src/types.js'

const ALL_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: false }

describe('generateCommonCases', () => {
  it('required=true: 欠落異常1件（query: 期待400）', () => {
    const cases = generateCommonCases(
      { type: 'string' },
      true,
      { paramIn: 'query', paramName: 'name', opts: ALL_OPTS }
    )
    const requiredCase = cases.find(c => c.keyword === 'required')
    expect(requiredCase?.expectedStatus).toBe('400')
  })

  it('required=true path: 欠落異常1件（期待404）', () => {
    const cases = generateCommonCases(
      { type: 'string' },
      true,
      { paramIn: 'path', paramName: 'id', opts: ALL_OPTS }
    )
    const requiredCase = cases.find(c => c.keyword === 'required')
    expect(requiredCase?.expectedStatus).toBe('404')
  })

  it('required=false: 欠落ケースなし', () => {
    const cases = generateCommonCases(
      { type: 'string' },
      false,
      { paramIn: 'query', paramName: 'name', opts: ALL_OPTS }
    )
    expect(cases.find(c => c.keyword === 'required')).toBeUndefined()
  })

  it('type=integer: 型不正ケース inputValue が "abc"', () => {
    const cases = generateCommonCases(
      { type: 'integer' },
      false,
      { paramIn: 'query', paramName: 'count', opts: ALL_OPTS }
    )
    const typeCase = cases.find(c => c.keyword === 'type')
    expect(typeCase?.inputValue).toBe('"abc"')
  })
})
