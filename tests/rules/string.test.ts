import { describe, it, expect } from 'vitest'
import { generateStringCases } from '../../src/generator/rules/string.js'
import type { GenerateOptions } from '../../src/types.js'

const ALL_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: false }
const FULL_ENUM_OPTS: GenerateOptions = { includeNormal: true, includeAbnormal: true, enumFullCoverage: true }

describe('generateStringCases', () => {
  it('enum: デフォルト代表値1件 + 異常1件', () => {
    const cases = generateStringCases(
      { type: 'string', enum: ['active', 'inactive', 'deleted'] },
      { paramName: 'status', opts: ALL_OPTS }
    )
    const normal = cases.filter(c => c.perspective.startsWith('正常系'))
    const abnormal = cases.filter(c => c.perspective.startsWith('異常系'))
    expect(normal).toHaveLength(1)
    expect(normal[0].inputValue).toBe('active')
    expect(abnormal).toHaveLength(1)
    expect(abnormal[0].inputValue).toBe('__INVALID__')
  })

  it('enum: fullCoverage で全値 + 異常1件', () => {
    const cases = generateStringCases(
      { type: 'string', enum: ['a', 'b', 'c'] },
      { paramName: 'x', opts: FULL_ENUM_OPTS }
    )
    const normal = cases.filter(c => c.perspective.startsWith('正常系'))
    expect(normal).toHaveLength(3)
  })

  it('maxLength: 最大長（正常）+ 最大長+1（異常）', () => {
    const cases = generateStringCases(
      { type: 'string', maxLength: 5 },
      { paramName: 's', opts: ALL_OPTS }
    )
    const normal = cases.find(c => c.keyword === 'maxLength' && c.perspective.startsWith('正常系'))
    const abnormal = cases.find(c => c.keyword === 'maxLength' && c.perspective.startsWith('異常系'))
    expect(normal?.inputValue).toBe('aaaaa')
    expect(abnormal?.inputValue).toBe('aaaaaa')
  })

  it('minLength=0: 異常系なし', () => {
    const cases = generateStringCases(
      { type: 'string', minLength: 0 },
      { paramName: 's', opts: ALL_OPTS }
    )
    const abnormal = cases.filter(c => c.keyword === 'minLength' && c.perspective.startsWith('異常系'))
    expect(abnormal).toHaveLength(0)
  })

  it('minLength>0: 最小長-1（異常）', () => {
    const cases = generateStringCases(
      { type: 'string', minLength: 3 },
      { paramName: 's', opts: ALL_OPTS }
    )
    const abnormal = cases.find(c => c.keyword === 'minLength' && c.perspective.startsWith('異常系'))
    expect(abnormal?.inputValue).toBe('aa')
  })

  it('format: date の正常・異常サンプル', () => {
    const cases = generateStringCases(
      { type: 'string', format: 'date' },
      { paramName: 'd', opts: ALL_OPTS }
    )
    const normal = cases.find(c => c.keyword === 'format' && c.perspective.startsWith('正常系'))
    const abnormal = cases.find(c => c.keyword === 'format' && c.perspective.startsWith('異常系'))
    expect(normal?.inputValue).toBe('2024-01-01')
    expect(abnormal?.inputValue).toBe('not-a-date')
  })
})
