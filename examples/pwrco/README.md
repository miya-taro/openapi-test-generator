# v1/pwrco/set の試験セット

**実APIは未接続です。** このセットは確定した仕様に基づき、検証用HTTP APIと実PostgreSQLで確認しています。

- POST `/v1/pwrco/set`、JSON body。成功200・本文なし。
- site_id/location_idの少なくとも一方。両方はsite_id優先。
- typeは整数1/2、任意。省略するとSQL NULL。
- start_datetime/end_time/schedule、各要素のtime/valueは必須。scheduleは1件以上。
- 必須欠落・型違い・enum違反・空配列は400。異常系では保存先全列の前後比較を行う。
- y_pwrcoの主キーはsite_id, datetime。datetime←time、rate←value、start←start_datetime、end←end_time。既存行の更新ではなく追加。

## 使うファイル

- `openapi.json`: リクエスト制約と応答契約。
- `scenarios.json`: 正常18件＋異常20件の実行可能なDB確認設定。GUIの「DB確認設定ファイル」の参照から読み込めます。正常ケースは既存UIの「POST：配列から複数行への保存を照合する」と同じ定義です。

正常系は拠点3通り（siteのみ/locationのみ/矛盾する両方でsite優先）、type3通り（1/2/省略→NULL）、schedule1件/2件の組み合わせです。各ケースで200・空本文・全保存値・追加件数・既存行の非変更を確認します。

異常系は各必須項目欠落、拠点両方なし、各型/日時形式/enumの違反、空配列、および**1件目正常・2件目不正で部分保存しないこと**を確認します。ケース一覧はscenarios.jsonのnameから確認できます。任意項目の省略と、明示したJSON nullは区別しています。

## 実API向けの設定

1. 検証用PostgreSQLとAPIのURL・認証を設定します。
2. 例のsite_id=101とlocation_id=HOMEが同じ拠点、OTHERが別の拠点を指すよう、実在する値に変更します。location参照先は前のAPIと同じt_siteを例にしているので、必要ならテーブル・列を変更します。
3. 日時は既存主キーと重ならないものに変更します。固定ファイルの再実行で既存行と衝突させないでください。ツールはAPIが作った行を自動削除しません。
4. openapi.jsonを読み込み、DB確認でscenarios.jsonを選択します。準備→ケースレビュー→実行で結果・証跡を保存します。

日付と拠点をまとめて差し替える補助コマンドもあります（リポジトリルートで実行）。

```sh
python docs/pwrco_suite.py --start "2026-11-01T00:00:00+09:00" --site-id 101 --location HOME --other-location OTHER --output pwrco-cases.json
```

`--table`、`--site-table`で検証テーブル名を変更できます。コマンド自体はファイル生成のみで、DB/APIにアクセスしません。正常・異常ケースはそれぞれ別の日付を使います。日時は固定予約や自動確保ではないので、実際に未使用かは確認してください。

## 確認範囲と限界

- 検証専用DBで他の書き込みを止めます。全テーブルの差分を読むため、上限5000行です。
- DBの具体的な列型が未提示なので、検証用DBでは日時をtimestamptz、rateをnumericとして検証しています。実DBの型・精度によって必要な日時/数値の確認は別途行ってください。
- rateの業務上の最小/最大値、期間の前後関係、scheduleの期間内制約、件数上限、認証、存在しない拠点の扱いは未確定です。推測した試験は追加していません。
- 既存主キーとの衝突は「運用上発生しない」という指定により対象外。再実行時のデータ管理は別です。
- 異常レスポンスは元の「レスポンスボディなし」という定義に従っています。実APIが400時に本文を返す場合は、400のcontentをその仕様に変更してください。

## ツール側の検証

`runner/tests/test_pwrco_e2e.py`で38ケース、既存UIの生成処理との一致、CLIのExcel/JUnit/JSON証跡を確認します。15種類の故障（優先拠点、欠落、余分、別行の値、rate、start、end、type、datetime、余計な本文、status、既存変更、既存削除、400時のDB変更、配列前半だけの部分保存）を注入して不合格になることも確認します。

`gui/tests/test_browser_pwrco.py`で、この設定ファイルを実ブラウザから読み込み、38件のレビュー・実行・Excel取得を確認します。試験が作るテーブルはランダム名の使い捨てテーブルで、実y_pwrcoは変更しません。
