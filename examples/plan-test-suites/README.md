# 計画APIの追加試験セット

UIの既存のファイル選択から読み込める設定です。対象はローカルの検証用APIとPostgreSQLです。業務APIへの接続・合格を示すものではありません。

## 読み込むファイル

| ファイル | 用途 |
| --- | --- |
| `plan-post-openapi.json` | 計画POSTの仕様・正常入力例・異常時のDB変更なし確認範囲。契約試験の自動生成に使う |
| `plan-post-scenarios.json` | POSTの正常25件と、途中保存を禁止する異常3件。DB確認設定として読み込む |
| `plan-get-scenarios.json` | GETの拠点・correct・typeの27組み合わせと期間境界5件。DB確認設定として読み込む |
| `../login/failure-scenarios.json` | ログインの不正資格情報・空文字5件。401は検証用APIの明示的な仮定 |

POSTは `plan-post-openapi.json`、GETは `../plan-get/openapi.json` を「対象を登録」で選択し、対応するシナリオファイルをDB確認設定として読み込みます。接続先URL・PostgreSQL・ログインを設定して準備→レビュー→実行してください。POSTの生成した契約試験とDB確認設定の試験は別の実行対象です。後者だけを実行しても契約試験220件は実行されません。

ファイル内の拠点・日付・テーブル名は例です。POSTは101/LOC001と202/LOC002、GETは101/HOMEと202/OTHERを使用しています。実際の参照先に合わせて変更してください。全行の前後比較を使うため、他の処理が同時更新しない専用の検証DBで使用します。既存行を自動削除する設定はありません。

## 追加した確認

- POST正常: 拠点3通り×type2通り×correct2通り×force2通りの24件と、1日・control1件の1件。日・controlごとに異なる値を送り、親子を取り違えた保存も検出します。correctの値による業務処理や保存先は未確定なので、correctの保存照合は含めません。
- POST異常: 生成された220件の必須・型・null・enum・日時形式・空配列・Content-Type違反を実HTTPで実行。正常リクエスト例を基準に変更し、保存先と拠点参照テーブルの変更がないことを確認します。これに2件目controlのtime欠落、2日目profit欠落、2日目controls空配列の3件を追加しています。
- POST故障検出: 不正入力でも200を返すAPI、先頭だけ保存して400を返すAPI、既存値を変えて400を返すAPIを不合格にします。
- GET正常: 拠点3通り×correct（省略/false/true）×type（省略/1-1/2-1）の27件と期間境界5件。開始時刻ちょうど、開始直前、終了ちょうど、終了直前、日付またぎ、同一期間のUTC表現を確認します。
- GET優先順位: correct/forceの優先、fixedの優先、fixed時のcpbs_type有無と大小、非fixed時のNULL優先、同順位のcreated降順を、既知の勝者42・敗者99を持つ専用データで確認します。期待SQLとAPIの選択処理は別実装です。
- GET0件: ツールの実行試験で200＋空配列と400の双方を確認します。`empty_get_case()`は期待statusと期待bodyの指定を必須としています。実API用の32件には0件時の未確定仕様を混ぜていません。

## 確定していない範囲

GETは既存の検証例の `start <= datetime < end` を使います。PHPコードの完全な再現ではなく、type省略時の選択などは `docs/sql-response-testing.md` に記載した例示ルールです。既知データで確認する7件もその範囲に限定します。

POSTの空配列400は例の `minItems: 1` に基づきます。実APIで許されるenum・配列件数・数値の桁あふれや丸め・correct_point省略時の保存・404/500を発生させる条件は仕様に合わせて設定してください。DB列がnumeric(15,3)であることだけから、APIが桁あふれを400として拒否するとは判断しません。

ログインの空文字・認証失敗status、GETの0件status、未知拠点、トークン期限切れは推測しません。pwrcoの既存主キー衝突と大量データ・負荷試験は、これまでの合意どおり今回の追加対象外です。

## 再生成と検証

```sh
python -m docs.plan_test_suites --output-dir examples/plan-test-suites
```

専用PostgreSQLの接続情報を `OTG_INTEGRATION_DB_CONFIG` に設定して実行します。

```sh
PYTHONPATH=.:runner python -m pytest runner/tests/test_plan_coverage_e2e.py runner/tests/test_three_api_auth_e2e.py runner/tests/test_login_e2e.py -q -s
```

`OTG_PLAN_COVERAGE_EVIDENCE_DIR` と `OTG_THREE_AUTH_EVIDENCE_DIR` で証跡の保存先を指定できます。前者には送信curl・判定・DB変更なしの結果、および境界・優先順位・故障検出のJSON、後者には認証付きのJSONとCLIのExcel/JUnitを保存します。CIでも追加試験を実行し、`measure-get-evidence` に保存します。
