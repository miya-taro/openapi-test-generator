import { describe, it, expect } from 'vitest'
import { generateIntegerCases } from '../../src/generator/rules/integer.js'
import type { GenerateOptions } from '../../src/types.js'

const ALL_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: false }
const NORMAL_ONLY: GenerateOptions = { includeNormal: true, includeAbnormal: false, enumFullCoverage: false }
const ABNORMAL_ONLY: GenerateOptions = { includeNormal: false, includeAbnormal: true, enumFullCoverage: false }

describe('generateIntegerCases', () => {
  it('minimum のみ: 正常1件 + 異常1件', () => {
    const cases = generateIntegerCases({ type: 'integer', minimum: 5 }, { paramName: 'n', opts: ALL_OPTS })
    expect(cases).toHaveLength(2)
    expect(cases[0].inputValue).toBe('5')
    expect(cases[1].inputValue).toBe('4')
  })

  it('maximum のみ: 正常1件 + 異常1件', () => {
    const cases = generateIntegerCases({ type: 'integer', maximum: 100 }, { paramName: 'n', opts: ALL_OPTS })
    expect(cases).toHaveLength(2)
    expect(cases[0].inputValue).toBe('100')
    expect(cases[1].inputValue).toBe('101')
  })

  it('minimum + maximum: 正常3件 + 異常2件 = 5件', () => {
    const cases = generateIntegerCases(
      { type: 'integer', minimum: 0, maximum: 100 },
      { paramName: 'n', opts: ALL_OPTS }
    )
    expect(cases).toHaveLength(5)
    const midCase = cases.find(c => c.keyword === 'minimum+maximum')
    expect(midCase?.inputValue).toBe('50')
  })

  it('excludeNormal: 異常系のみ', () => {
    const cases = generateIntegerCases(
      { type: 'integer', minimum: 1, maximum: 10 },
      { paramName: 'n', opts: ABNORMAL_ONLY }
    )
    expect(cases.every(c => c.perspective.startsWith('異常系'))).toBe(true)
  })

  it('excludeAbnormal: 正常系のみ', () => {
    const cases = generateIntegerCases(
      { type: 'integer', minimum: 1, maximum: 10 },
      { paramName: 'n', opts: NORMAL_ONLY }
    )
    expect(cases.every(c => c.perspective.startsWith('正常系'))).toBe(true)
  })

  it('_exclusiveMinimumValue: 境界値（異常）+ 境界値+1（正常）', () => {
    const cases = generateIntegerCases(
      { type: 'integer', _exclusiveMinimumValue: 10 },
      { paramName: 'n', opts: ALL_OPTS }
    )
    const abnormal = cases.find(c => c.perspective.includes('exclusiveMinimum境界値'))
    const normal = cases.find(c => c.perspective.includes('exclusiveMinimum超過値'))
    expect(abnormal?.inputValue).toBe('10')
    expect(normal?.inputValue).toBe('11')
  })

  it('multipleOf: 倍数（正常）+ 非倍数（異常）', () => {
    const cases = generateIntegerCases(
      { type: 'integer', multipleOf: 3 },
      { paramName: 'n', opts: ALL_OPTS }
    )
    const normal = cases.find(c => c.keyword === 'multipleOf' && c.perspective.startsWith('正常系'))
    const abnormal = cases.find(c => c.keyword === 'multipleOf' && c.perspective.startsWith('異常系'))
    expect(normal?.inputValue).toBe('6')
    expect(abnormal?.inputValue).toBe('4')
  })
})
