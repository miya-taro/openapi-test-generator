import { writeFile } from 'node:fs/promises'
import type { TestCase } from '../types.js'

export interface OutputJson {
  meta: {
    generatedAt: string
    source: string
    totalCases: number
    normalCases: number
    abnormalCases: number
  }
  cases: TestCase[]
}

export function buildOutput(cases: TestCase[], source: string): OutputJson {
  const normalCases = cases.filter(c => c.perspective.startsWith('正常系')).length
  const abnormalCases = cases.filter(c => c.perspective.startsWith('異常系')).length

  return {
    meta: {
      generatedAt: new Date().toISOString(),
      source,
      totalCases: cases.length,
      normalCases,
      abnormalCases,
    },
    cases,
  }
}

export async function writeOutput(output: OutputJson, outputPath: string): Promise<void> {
  const json = JSON.stringify(output, null, 2)
  await writeFile(outputPath, json, 'utf-8')
}
