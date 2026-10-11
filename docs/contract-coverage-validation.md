# 契約試験の生成漏れ・誤判定の検証

対象は、人がOpenAPIまたはUIで定義したJSON APIの契約です。仕様にない業務上の正解、DBとの対応、権限別の期待結果は推測しません。

## 今回修正した漏れ

| 観点 | 変更後 |
| --- | --- |
| JSONの型 | 文字列に数値・真偽値・配列・object、整数に小数など、許可されない型を実際のJSON型のまま送信 |
| 配列要素の型 | `items: string[]` に数値を含む配列も生成 |
| enum / const | 整数・boolean等も含めて許可値と、同型で許可されない値を生成。他の制約も確認 |
| 数値の複合制約 | minimum/maximum/multipleOfを同時に満たす境界値・中間値を選ぶ |
| 狭い小数区間 | 固定幅の加減算で区間外になる誤りを修正 |
| integer + multipleOf: 1 | 存在しない「整数の非倍数」を異常系にしない |
| oneOf / anyOf | 各分岐の型別ルールも適用。別分岐が許可する値を異常系にしない |
| additionalProperties | 追加項目がstringの場合にも数値の不正入力を生成 |
| JSONレスポンス | `NaN`、`Infinity`、`-Infinity` をJSONとして拒否 |

入力値の内部表現 `__JSON_VALUE__...` はJSON型を保持するためのものです。通信時にはマーカーを除いたJSON値を送ります。例えば `__JSON_VALUE__123` は文字列 `"123"` ではなく数値 `123` です。

## 再実行できる検証

`runner/tests/test_contract_coverage_audit.py` を通常のCIに含めています。

- 22種類の定義について、独立に列挙した104観点に該当する**実際に組み立てたリクエスト**が存在することを検証。
- 生成された全入力と期待結果を元のJSON Schemaと照合し、正しいHTTP APIが全件合格することを確認。
- 文字列に数値を許可、integer enum無視、boolean enum無視、oneOf文字列分岐の最大長無視、の4種類の不具合を検出。
- 計測API（GET・JSONボディ）では、location_idに数値を許可、itemsに数値を許可、site_idに小数を許可、の3種類の不具合を検出。
- レスポンス本文、必須ヘッダ、ステータス、形式を独立に確認する47観点を検証。
- site_id/location_idの少なくとも一方必須とstart/endの同時指定は、各4通りを確認。

```bash
python -m pytest runner/tests/test_contract_coverage_audit.py -q
```

詳細JSONエビデンスを保存する場合:

```bash
OTG_AUDIT_OUTPUT=.artifacts/contract-coverage python scripts/contract_case_audit.py
OTG_AUDIT_OUTPUT=.artifacts/contract-coverage python scripts/contract_response_audit.py
```

## 「合格」と「試験項目が揃っている」は別

画面・ケースJSON・Excelの「対応状況」で、正常側/異常側、enumの各値、不正なJSON型、body全体の欠落、認証を別々に確認できます。例えば最小値の正常ケースだけ生成できても、異常側は「未生成」と表示します。

| 表示 | 意味 |
| --- | --- |
| ケース生成済み | その観点のケースがある。実行・合格・全組み合わせの網羅は別 |
| 未生成 | 観点はあるがケースがない。制約の組み合わせや生成設定も要確認 |
| 未対応 / 一部対応 | 専用ケースや全分岐・全組み合わせの生成を保証しない |
| 該当なし | 0未満の配列長など、仕様上存在しない観点 |
| 実行時検証 | 返ったレスポンスを検証する。全応答分岐が実行されたという意味ではない |

104観点の合格は、あらゆるAPI・JSON Schemaに漏れがない証明ではありません。特に複雑な入れ子の条件分岐、専用生成ルールのないSchemaキーワード、認証AND条件の一資格情報だけ欠落/無効、OR認証の各選択肢、scope別の権限試験は、未生成・一部対応として残ります。認証の全欠落・全無効ケースだけで個別認証を試験済みに数えません。

DB試験は、別途人が定義したPostgreSQL/InfluxDB 1.xの対応付けと条件を照合します。大量データ・性能試験、仕様のない業務ロジックはこの契約試験の網羅範囲に含めません。
