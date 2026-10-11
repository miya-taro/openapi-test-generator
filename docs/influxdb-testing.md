# InfluxDB 1.xをUIから照合する

対応対象DBはPostgreSQLと **InfluxDB 1.x（InfluxQL）** です。MySQL／SQL ServerおよびInfluxDB 2.x／3.xは今回の対象外です。

## GETレスポンスを期間内の全ポイントと比較

1. OpenAPIを読み込み、詳細設定で「InfluxDBを使う」を選び、host・port・databaseと必要な認証情報を入力。
2. 「DB確認」でGET操作を選び、確認するDBを「InfluxDB 1.x」にする。
3. テーブル / measurement欄に対象measurementを入力。
4. 検索項目に、送信する値、DBのtime・タグ・フィールド名、比較演算子を入力。
5. レスポンス項目に対応するDB項目を入力して、対応設定を追加・保存。
6. ケースを準備し、確認・承認して実行。結果Excel・比較証跡から期待ポイントと実際の応答を確認。

例：`/v1/result/measure/get`（GET・JSON body）

| API入力 | InfluxDB項目 | 比較 |
|---|---|---|
| site_id | site（整数フィールド） | =、location_idと同じORグループ |
| location_id | location（タグ） | =、site_idと同じORグループ |
| start | time | >=（仕様が開始を含む場合） |
| end | time | <=（仕様が終了を含む場合） |
| items | item（タグ） | IN |

`result[].time → time`、`result[].item → item`、`result[].value → value`を対応付けます。
レスポンスの順序は問いませんが、件数・各値・重複数まで比較します。timeはタイムゾーンの違いを吸収し、ナノ秒の差は保持します。

Bodyの値は利用者が指定します。条件付き必須とIN配列の組み合わせ生成はPostgreSQLと共通です。
Query / Pathの値は、従来のDB対応画面と同様、明示されたDB列の既存データから境界確認用の値を選びます。対応列や仕様そのものは推測しません。

条件を外したときに増えるポイント、開始終了の境界、各IN要素、各OR分岐を識別できる既存ポイントが必要です。十分なデータがなければHTTP送信前に「未確認」とし、合格にはしません。試験データの自動投入はありません。

## API実行前後で変更がないことを確認

「DB確認」で、確認する内容を「API実行前後でDBに変更がないこと」にします。
InfluxDBでは、measurement・比較する項目・等値条件に加え、タイムゾーン付きの固定開始／終了日時（両端を含む）を入力します。
`now() - 5m`のように実行中に動く範囲は使わず、前後で同じ期間を比較します。

比較項目には `time` とポイントを識別する全タグも含めてください。指定しない項目は比較しません。
GET / POST / PUT / PATCH / DELETEで利用できます。POST等の成功時に変更が必要なことを判定するモードではありません。

通常の契約試験で、自動生成する異常系すべてに前後比較を付ける場合は、契約編集の「自動生成する異常系でDBが変わらないことを確認」に同じ範囲を設定します。OpenAPIへの保存形式は次の通りです。

```json
"x-otg-error-db-unchanged": [{
  "engine": "influxdb",
  "table": "measure",
  "columns": ["time", "location", "item", "value"],
  "where": {},
  "time_start": "2026-01-01T00:00:00Z",
  "time_end": "2026-01-02T00:00:00Z"
}]
```

InfluxDBだけの接続設定でも実行できます。異常系の前後ポイントは `test-result-db-evidence.json`、個別DB確認の証跡は通常のDB比較エビデンスに残ります。

## 対応範囲と制限

- 1回の照合上限は5,000ポイント。上限を超えて切り捨てた結果を合格にしません。Query / Pathの自動値選択元も同じ上限です。
- 未定義のmeasurement・項目、未取得・接続失敗、条件確認用データ不足は合格にしません。
- 行条件のnullは非対応。タグは文字列、timeはタイムゾーン付き日時で指定します。型変換・集計・JOINは行いません。
- 前後比較は他の書き込みがない検証用範囲で実行してください。非同期反映待ち・DB復旧・テストポイントの投入／後片付けはありません。
- 今回追加した値照合UIはGET対象です。InfluxDBのPOST／PUT／PATCH／DELETEの保存・更新・削除期待値を作るUIは未対応と明示して停止します。既存YAMLの最新1ポイント検証は従来どおり利用可能です。
- PostgreSQL設定の既定値と既存ファイル形式は維持します。

## 検証（2026-10-12 日本時間）

実InfluxDB **1.8.10** と独立したHTTP APIを使い、UIの生成関数から出力した設定をCLIで実行しました。

- 正常な条件組み合わせ18件、順序逆転、同じ時刻を異なるタイムゾーンで返すAPIが合格。
- 条件無視・OR→AND・境界除外・IN先頭だけ・欠落・重複・値違い・1ns違いの12種類を不合格として検出。
- 条件確認用データが不足した場合は「未確認」、HTTP未送信。
- 5メソッドの前後変更なし確認が合格。
- 自動生成異常系20件がDB変更なしで合格。更新・挿入・削除を起こす同じ20件×3種の計60件を不合格として検出。
- 実Chromiumで、UIからGET対応を入力→18件生成→保存、異常系比較範囲を設定→OpenAPI保存→再読込を確認。
- 全117 HTTP呼び出し。ExcelとJSON証跡を出力。利用者の実API・実DBは未検証。

再現するには検証用InfluxDBを起動し、次の環境変数で結合試験を実行します。試験は一意な専用databaseを作成して最後に削除します。

```bash
OTG_INFLUX_INTEGRATION_CONFIG='{"host":"127.0.0.1","port":8086}' \
OTG_INFLUX_EVIDENCE_DIR=/tmp/influx-evidence \
python -m pytest runner/tests/test_influx_response_e2e.py -q
```
