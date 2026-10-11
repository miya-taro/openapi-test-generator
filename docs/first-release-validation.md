# 初版の動作検証（2026-10-12 日本時間）

検証用APIは `release_candidate_api.py` に独立実装し、ツールの生成器やOpenAPIの検証関数を入力検証に流用していません。仕様は `release_candidate_openapi.json` に別途定義しています。これにより、生成器とAPIが同じ不具合を共有して合格することを避けます。

## HTTP契約試験

| 検証対象 | 件数 | 主な観点 |
|---|---:|---|
| GET検索 | 21 | 整数・真偽値・繰り返しクエリ配列 |
| GETパス | 7 | enum、空白・日本語を含むURL |
| POST入れ子オブジェクト | 42 | 必須、型、長さ、pattern、入れ子、配列 |
| POSTルート配列 | 18 | min/maxItems、uniqueItems、小数、multipleOf |
| PUT置換 | 24 | 全項目必須、nullable、空文字、true/false |
| PATCH部分更新 | 24 | 任意項目省略、minProperties、true/false |
| DELETE | 9 | ID境界、204の空レスポンス |
| GETヘッダ・Cookie | 11 | 必須、送信位置、値の制約 |
| GET認証 | 3 | 正常トークン、認証なし、無効トークン、401/403 |
| 空配列の成功応答 | 1 | 空配列、date-time |
| 空データを400とする仕様 | 1 | 人が明示した期待status |
| application/problem+json | 1 | 明示した422とJSON schema |
| **合計** | **162** | 12操作、GET/POST/PUT/PATCH/DELETE |

成功APIの合格に加え、同じ入力を故障APIへ送り不合格になることを確認しました。15種類：500、定義外409、必須ヘッダ欠落、ヘッダ型違反、Content-Type違反、必須項目欠落、型違反、入れ子の違反、余分な項目、配列要素違反、許可しないnull、不正日時、不正JSON、認証無視、入力検証無視。

空データ時の200/400はAPI仕様で変わります。ツールが一律に400を期待することはありません。成功応答が定義されていない操作には200の正常ケースを捏造せず警告します。

## DBと画面

- 実InfluxDB 1.8.10でGET照合・異常系の副作用・単一ポイントの保存／更新／削除を確認。正常4メソッド、故障検出13ケース、前提不足によるHTTP未送信4ケースを追加。実画面のPOST設定→保存→承認→実行→Excel取得も確認。詳細は [InfluxDB検証記録](influxdb-testing.md)。
- 実HTTP＋PostgreSQLの既存3系統を再実行：GET＋JSONボディの拠点・期間・items抽出、CRUD、項目間大小条件、更新してはいけないDB行の保持。
- DBの故障注入では、誤更新・誤削除・余分な挿入等16種類を検出。28シナリオでNULL・比較範囲・行数上限も確認。
- Chromiumで実画面を操作：OpenAPI取込→対象選択→ケース準備→レビュー→承認→実行→Excelダウンロード。正常→不正日時の検出→失敗ケース再実行による回復まで確認。画面表示とExcelの判定を照合。
- Windows CIでは `run-windows.bat -SmokeTest` を2回実行し、初回依存準備・再起動・HTTPによる画面取得・PythonブリッジでのOpenAPI取込を確認。通常起動と同じ準備処理を使い、ブラウザーの自動表示だけ省略して終了します。

## 修正した問題

配列境界で重複や不正要素を作る、required文字列の空文字を常に異常扱いする、PATCHの省略がminProperties違反になる、booleanのfalse正常ケース不足、認証の401/403両定義を扱えない、成功応答未定義でも200を期待する問題を修正しました。

実ブラウザー試験で、結果Excelの合否が空白、失敗時の結果ダウンロード不可、失敗ケース再実行ボタンの有効化タイミングも修正しました。仕様Excelは書き換えず、結果Excelへ自動判定を保存します。

## 再実行

```bash
python -m pytest runner/tests/test_release_candidate_matrix.py -q
npm ci --prefix gui-tauri
npm run build --prefix gui-tauri
pip install -r requirements-browser-test.txt
python -m playwright install --with-deps chromium
OTG_BROWSER_TEST=1 python -m pytest gui/tests/test_browser_workflow_e2e.py -q
```

Windowsの起動確認：`run-windows.bat -SmokeTest`。Python 3.10以降とNode.js 22.12以降が必要です。

`OTG_RELEASE_EVIDENCE_DIR` と `OTG_BROWSER_EVIDENCE_DIR` で証跡保存先を指定できます。CIの `first-release-evidence` にはHTTP判定JSON、故障検出JSON、画面スクリーンショット、ダウンロードしたExcelを保存します。DB証跡は `measure-get-evidence` に保存します。

## この検証で保証しないこと

- ユーザーの実API・実DBに対する試験は未実施。接続情報、承認済みの契約、テストデータが必要です。
- Windows CIの起動成功は個々のPCのアプリ制御ポリシーへの対応を保証しません。署名なしexeの配布確認とも異なります。
- 大量データ・負荷・性能、複雑なJOINや業務計算の自動推測は初版対象外です。
- この記録は検証済み範囲を示します。あらゆるOpenAPIキーワード・組み合わせ・全APIへの対応完了を意味しません。
