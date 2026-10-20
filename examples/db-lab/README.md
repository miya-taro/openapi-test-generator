# APIとDBを連携させる検証用サービス

PostgreSQL 16とInfluxDB 1.8.10に実際に読み書きするHTTP APIです。
ツールの入力検証・SQL生成・期待値生成処理をAPI実装に流用せず、別々に実装しています。
正常なAPIだけでなく、値の誤り・未保存・余分な変更などを起こすAPIを同じ試験で確認できます。
検証専用です。認証用ユーザーとパスワードは公開されたダミー値で、実運用には使いません。

## 起動して自動検証する

リポジトリ直下で実行します。Python 3.10以降とDocker Composeが必要です。
ツールの通常起動にはDockerは不要ですが、この検証環境では実DBを起動するために使います。

```sh
python -m pip install -r requirements-runtime.txt
docker compose -p otg-db-lab -f examples/db-lab/compose.yaml up -d --wait
python docs/run_db_lab.py --legacy --output-dir .artifacts/db-lab-run1
```

`--legacy`を付けると、既存の計画POST・計画GET・pwrco用サービスも起動して試験します。
別々の専用テーブルを使うため、同じDBでもお互いのデータを参照しません。
`--legacy`なしでは新しいサービスの試験だけを実行します。

自動検証が終了するとHTTPサービスを停止し、その実行用に作ったテーブルとInfluxDBのdatabaseを削除します。
DBコンテナ自体は残るため、出力先を変えて再実行できます。証跡は上書きしません。
不要になったら、次のコマンドでこのプロジェクトのコンテナとボリュームだけを削除します。

```sh
docker compose -p otg-db-lab -f examples/db-lab/compose.yaml down -v
```

DBはホストの`127.0.0.1:15432`と`127.0.0.1:18086`で待ち受けます。
ポートが使用済みの場合はCompose設定と`config.json`を合わせて変更してください。
`--config`で別の接続ファイルも指定できますが、必ず検証専用DBを使ってください。

## APIを起動したままUIから試す

```sh
python docs/run_db_lab.py --serve --output-dir .artifacts/db-lab-manual
```

起動ログと出力先の`connection.json`にBase URLを表示します。
以下は同じ出力先に作成されます。

| ファイル | 用途 |
| --- | --- |
| `openapi.json` | UIに取り込むAPI定義 |
| `scenarios.json` | この起動で作った実テーブル・measurementとの対応設定 |
| `db-config.json` | この起動用のDB接続設定。実環境の資格情報を設定した場合は共有しないこと |
| `auth.json` | ログインしてレスポンスの`id`を`auth-key`へ設定する定義 |
| `connection.json` | Base URL、実テーブル名、InfluxDB database名 |

ログインは`POST /v1/auth/login`、usernameは`fixture-user`、passwordは`fixture-password-only`です。
サービス停止まで同じ認証IDを使用します。認証の期限切れ・更新を再現するサービスではありません。
`Ctrl+C`で停止すると専用データも削除されるため、次回起動時は新しい設定ファイルを取り込んでください。
書き込みケースはDB状態を変えます。手動で全ケースを繰り返す場合はサービスを再起動してください。
自動検証モードでは初期化を行い、同じスイートを2回実行して確認しています。

## 用意したAPI

| 操作 | 確認できること |
| --- | --- |
| POST `/v1/auth/login` | 正しい資格情報、不正パスワード、取得したIDによる後続API認証 |
| GET `/v1/records` | DB全行の値・件数・重複・欠落。配列順は不問 |
| GET `/v1/records/{id}` | 主キーによる1件取得、404 |
| POST `/v1/records` | 小数、false、JSONBの入れ子、NULL、重複409、入力異常400とDB不変 |
| PUT `/v1/records/{id}` | 全項目の置換、対象外の行を維持 |
| PATCH `/v1/records/{id}` | 部分更新、未指定の値を維持 |
| DELETE `/v1/records/{id}` | 対象行の削除、対象外の行を維持、204の空本文 |
| GET `/v1/measurements/get` | JSONボディ、PostgreSQLの拠点参照→InfluxDBの期間・items検索、複数ID、0件 |
| POST / PUT / PATCH / DELETE `/v1/point` | InfluxDB単一ポイントの保存・更新・削除、初期データ準備と後片付け |

計測値の期間は`start < time <= end`、該当拠点0件なら`200`と空配列という**この模擬API固有の仕様**です。
利用者のAPIへ同じ仕様を強制するものではありません。
作成→レスポンスIDで取得→削除するAPI連続実行も試験します。

## APIと故障ケースの追加方法

1. `docs/db_lab_service.py`に独立したHTTP処理とDB処理を追加する。
2. `docs/db_lab_cases.py`の`specifications()`に契約を、`scenarios()`に人が決めたDB対応・期待値を追加する。
3. `faulty_cases()`に、不正なAPI動作と検出すべき試験の組み合わせを追加する。期待値を故障版に合わせて変更しない。
4. 自動検証を実行し、正常系の合格と故障検出の両方を確認する。
5. 操作やケースを追加した場合は、`runner/tests/test_db_lab_e2e.py`の件数と仕様の説明を更新する。

故障モードは検証スクリプト内でのみ切り替えます。HTTP経由の故障切り替えAPIはありません。
試験対象と期待値の双方が同じバグを持つ可能性を減らすため、API内部でツールの検証器を呼ばないでください。

## 証跡・継続的な検証

実行グループごとに`result.xlsx`、`result.json`、`junit.xml`、`run.log`、実際のケース定義を保存します。
Excelには結果サマリー、DBシナリオ結果、送信リクエスト、API手順、DB比較詳細を出力します。
`summary.json`は期待した合否と実測の合否を区別します。故障モードの`failed`は期待した不合格です。
全件が期待どおりでない限り実行スクリプトは成功終了しません。

CIの実PostgreSQL／InfluxDBジョブにも回帰試験を追加しました。DB接続環境変数がない通常の単体テストではskipになります。
skipを検証成功とは数えません。今回の実行結果と限界は[検証報告書](../../docs/db-lab-validation.md)を参照してください。
