# POSTの配列から複数行への保存を照合する

「DB確認」→「確認する内容」→「POST：配列から複数行への保存を照合する」で設定します。PostgreSQLのINSERTが対象です。OpenAPIの入力制約の試験は、通常の契約試験で別途実行します。

## 計画保存の設定例

`examples/plan-post-openapi.json`と`examples/plan-post-request.json`は、2日分・各2controlの検証例です。URLは仮の`/v1/plan/set`、enumは例示の`1-1`と`2-1`、配列の最小件数は1です。実APIのURL、認証、全enum値、件数制約に合わせて変更してください。〇の項目は各階層で必須、site_id/location_idは少なくとも一方が必須です。correct_point以下は必須にしていません。

1. 対象POST、PostgreSQL、保存先テーブルを選択する。
2. 「1行に対応する配列」で`plans[].controls[]`を選択する。
3. 主キーに`datetime,created,site_id,use_id`を指定する。実DBの主キーと照合し、不一致ならAPI実行前に停止する。
4. 保存列の対応を入力する。「計画保存の対応例を設定」で下表の例を入力できる。これは明示的に選択する例で、DBからの推測ではない。
5. 送信するJSON、期待する成功status、本文なしを設定し、保存→準備→レビュー→実行する。

| DB列 | 期待値の指定 |
| --- | --- |
| datetime | plans[].dateの日付とplans[].controls[].time、Asia/Tokyoを組み合わせる |
| created | HTTP呼出し開始〜完了の時刻。前後の許容秒数を人が指定（例は5秒） |
| site_id | site_idが指定されていれば優先。なければlocation_idを参照元t_site.location_idと等価検索し、site_idを1件取得する |
| use_id | type（文字列enum。DB列も文字列を保存できる型が必要） |
| profit | plans[].profit |
| buy / sell / charge / discharge / soc / gen / suppression | 同じcontrolの同名項目 |
| force | リクエストのforce。true/falseをそのまま比較 |
| manual / fixed | false |
| cpbs_type | 0 |
| correct_point | 同じcontrolのcorrect_point全体をJSONとして比較 |

`correct`の保存ルールは今回定義していないため、対応例には含めていません。各DB列を追加・編集・削除でき、他のAPIにも同じ機能を利用できます。

correct_pointなど任意項目の省略時は、既定では期待値未設定として停止します。「DBのNULLを期待」はAPI仕様がそうである場合に人が選択してください。丸め・デフォルト値・保存しない条件は推測しません。

## 合否判定

- 元のリクエストをそのまま送信する。site_id優先の参照は期待値作成用で、送信内容を書き換えない。
- 保存対象の全行を実行前後で読み、実際の複合主キーで今回の追加行を特定する。古い同値の行だけで合格にしない。
- 全期待行を一対一に照合する。順序は無視するが、欠落・余分な行・重複は検出する。
- 既存行の変更・削除も不合格にする。既存行を上書きするAPIは、このINSERT確認の対象ではない。
- 数値はDecimalで比較し、numeric(15,3)への保存時の丸めを勝手に期待値へ適用しない。JSONはキー順を無視し、配列順とboolean/数値の違いを保持する。
- 日付＋時刻は明示したタイムゾーンで組み立てる。日時の日付はそのゾーンへ変換して取り出す。夏時間で曖昧・存在しない時刻は停止する。
- createdは設定した許容時間内か確認する。ツール実行端末とAPIサーバーの時計を合わせる。
- OpenAPIの応答定義にcontentがない場合は本文が厳密に空か確認する。空白、`{}`、`null`も本文ありとして不合格。UIの「レスポンスボディなし」でこの定義を保存できる。

`db-scenario-evidence.json`の`db_insert_comparison`に対応定義、参照結果、前後の行、期待行、追加行、未一致行、変更された既存行、実行時刻、判定を保存します。Excel・JUnit・HTMLとUIにも合否を反映し、NG時も結果Excelを開けます。設定変更は試験ID・レビュー対象に反映されます。

## 検証環境と制限

比較は保存先テーブル全体です。検証専用DBで他処理の書き込みを止めてください。同時書き込みと当該APIの書き込みを識別する仕組みではありません。比較前後の最大行数は5000、期待行の最大数は1000。超過時に切り捨てて合格にはしません。

ツールの比較処理は読み取り専用です。対象APIが追加した行は自動削除しません。必要な片付けは既存の試験後SQLなどで、検証環境に合わせて明示してください。非同期反映待ち、UPDATE/UPSERT、複数テーブルへの一括保存、任意の業務計算はこの機能の対象外です。

## 実証

`runner/tests/test_post_array_e2e.py`はUI生成処理、実HTTP API、実PostgreSQLを使用します。2日×2control、siteのみ/locationのみ/両方（異なる拠点でsite優先）、force両値、文字列enum、日時、数値、JSONを確認します。16種類の故障（欠落、余分、重複、未保存、数値、親の値、JSON、日時、固定値、force、use_id、優先順位、created、余計な本文、既存変更、既存削除）を検出します。

`gui/tests/test_browser_post_array.py`は実Chromiumで設定・保存・レビュー・実行・成功/失敗のExcel取得まで検証します。これらをCIでも実行して証跡を保存します。
