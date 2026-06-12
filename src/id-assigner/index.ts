import type { TestCase } from '../types.js'
import { logger } from '../logger.js'

const SORT_ORDER_IN: Record<string, number> = {
  path: 0,
  query: 1,
  header: 2,
  cookie: 3,
  body: 4,
}

export function assignIds(cases: Omit<TestCase, 'id'>[]): TestCase[] {
  // operationId の重複を検出して _2, _3 サフィックスを付与
  const opIdCount = new Map<string, number>()
  const opIdMap = new Map<string, string>()

  for (const tc of cases) {
    const rawId = tc.operationId
    if (!opIdMap.has(rawId)) {
      const count = opIdCount.get(rawId) ?? 0
      opIdCount.set(rawId, count + 1)
      if (count === 0) {
        opIdMap.set(rawId, rawId)
      } else {
        opIdMap.set(rawId, `${rawId}_${count + 1}`)
        logger.warn({ operationId: rawId }, 'operationId 重複 → サフィックス付与')
      }
    }
  }

  // operationId ごとにグルーピング → ソート → 連番付与
  const groups = new Map<string, Omit<TestCase, 'id'>[]>()

  for (const tc of cases) {
    const key = tc.operationId
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(tc)
  }

  const result: TestCase[] = []

  for (const [opId, group] of groups) {
    const resolvedOpId = opIdMap.get(opId) ?? opId

    const sorted = group.slice().sort((a, b) => {
      // in の順
      const inDiff = (SORT_ORDER_IN[a.in] ?? 9) - (SORT_ORDER_IN[b.in] ?? 9)
      if (inDiff !== 0) return inDiff
      // パラメータ名
      const nameDiff = a.paramName.localeCompare(b.paramName)
      if (nameDiff !== 0) return nameDiff
      // 正常/異常（正常系が先）
      const isAbnormalA = a.perspective.startsWith('異常系') ? 1 : 0
      const isAbnormalB = b.perspective.startsWith('異常系') ? 1 : 0
      return isAbnormalA - isAbnormalB
    })

    sorted.forEach((tc, idx) => {
      const seq = String(idx + 1).padStart(3, '0')
      result.push({
        ...tc,
        id: `TC-${resolvedOpId}-${seq}`,
      })
    })
  }

  return result
}
