import type { TestCase, AuthSpec } from '../../types.js'

type PartialCase = Omit<TestCase, 'id' | 'operationId' | 'path' | 'method' | 'in' | 'paramName' | 'verdict' | 'expectedResponseBody' | 'expectedResponseHeader' | 'expectedResponseTime'>

export function generateAuthCases(spec: AuthSpec): PartialCase[] {
  const invalidValue = spec.schemeType === 'bearer'  ? 'Bearer invalid-token-xxx'
    : spec.schemeType === 'basic'                    ? 'Basic aW52YWxpZA=='
    : 'invalid-token-xxx'

  return [
    {
      summary: `${spec.operationId} 認証なし（異常）`,
      keyword: 'auth',
      perspective: '異常系_認証なし',
      inputValue: '（認証ヘッダなし）',
      expectedStatus: '401',
      expectedResult: '認証エラーが返ること',
      notes: `${spec.headerName} ヘッダを送信しない`,
    },
    {
      summary: `${spec.operationId} 無効な認証トークン（異常）`,
      keyword: 'auth',
      perspective: '異常系_無効トークン',
      inputValue: invalidValue,
      expectedStatus: '401',
      expectedResult: '認証エラーが返ること',
      notes: `無効な ${spec.headerName} を送信する`,
    },
  ]
}
