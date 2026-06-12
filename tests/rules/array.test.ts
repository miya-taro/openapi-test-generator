import { describe, it, expect } from 'vitest'
import { generateArrayCases } from '../../src/generator/rules/array.js'
import type { GenerateOptions } from '../../src/types.js'

const ALL_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: false }

describe('generateArrayCases', () => {
  it('minItems: 最小要素数（正常）+ 最小要素数-1（異常）', () => {
    const cases = generateArrayCases(
      { type: 'array', minItems: 2, items: { type: 'string' } },
      { paramName: 'tags', opts: ALL_OPTS }
    )
    const normal = cases.find(c => c.keyword === 'minItems' && c.perspective.startsWith('正常系'))
    const abnormal = cases.find(c => c.keyword === 'minItems' && c.perspective.startsWith('異常系'))
    expect(normal?.inputValue).toBe('["a", "a"]')
    expect(abnormal?.inputValue).toBe('["a"]')
  })

  it('maxItems: 最大要素数（正常）+ 最大要素数+1（異常）', () => {
    const cases = generateArrayCases(
      { type: 'array', maxItems: 3, items: { type: 'integer' } },
      { paramName: 'ids', opts: ALL_OPTS }
    )
    const normal = cases.find(c => c.keyword === 'maxItems' && c.perspective.startsWith('正常系'))
    const abnormal = cases.find(c => c.keyword === 'maxItems' && c.perspective.startsWith('異常系'))
    expect(normal?.inputValue).toBe('[1, 1, 1]')
    expect(abnormal?.inputValue).toBe('[1, 1, 1, 1]')
  })

  it('uniqueItems: 重複要素（異常）のみ', () => {
    const cases = generateArrayCases(
      { type: 'array', uniqueItems: true, items: { type: 'string' } },
      { paramName: 'tags', opts: ALL_OPTS }
    )
    const abnormal = cases.find(c => c.keyword === 'uniqueItems')
    expect(abnormal?.perspective).toContain('異常系')
    expect(abnormal?.inputValue).toBe('["a", "a"]')
  })

  it('minItems=0 の場合異常系なし', () => {
    const cases = generateArrayCases(
      { type: 'array', minItems: 0 },
      { paramName: 'tags', opts: ALL_OPTS }
    )
    const abnormal = cases.filter(c => c.keyword === 'minItems' && c.perspective.startsWith('異常系'))
    expect(abnormal).toHaveLength(0)
  })
})
