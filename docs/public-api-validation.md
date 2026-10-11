# 公開APIでの検証（2026-10-11）

ローカルに作ったAPIに加え、外部で運用されている3サービスに対し、ツールの生成器・HTTPクライアント・検証器・Excel/JUnit出力を使用して確認しました。

| 公開API | 対象 | HTTP試験 | 結果 |
|---|---|---:|---|
| PyPI | requests/sampleprojectのメタデータ、バージョン指定、存在しないプロジェクト | 4 | 4 OK |
| npm registry | パッケージ・バージョン指定、検索、存在しないパッケージ | 5 | 5 OK |
| crates.io | serde/itoaのメタデータ、存在しないcrate | 3 | 3 OK |
| 合計 | GETのみ | 12 | 12 OK |

最終実行時刻：2026-10-11 13:25 UTC。200が9件、404が3件。

## 確認内容と範囲

- HTTPS経由でJSONを取得し、入れ子オブジェクト、配列要素、整数・文字列・boolean、date-time、Content-Typeを検証。
- 代表的な正常リクエスト4件は生成器の最小有効リクエスト。残り8件は公開データを指定した明示ケース。すべてを自動的に推測したわけではありません。
- 公開資料をもとに**一部項目の契約を人が定義したOpenAPI**を使用。各サービスの公式OpenAPI全体を網羅した試験ではありません。
- 保存した実応答に誤った期待ステータス・ボディ型を設定するオフライン確認6件も実施し、すべてNG。追加のHTTP送信や公開APIへの故障注入はしていません。
- 公開APIのDB内部、POST/PUT/PATCH/DELETE、ログイン認証、負荷試験は今回の対象外。これらの検証結果とは区別します。

## 見つかった問題

### ツール側：環境のCA設定がHTTPS送信へ反映されない

通常の `requests.get()` は成功する一方、本ツールの `PreparedRequest`＋`Session.send()` では `REQUESTS_CA_BUNDLE` 等を引き継がず、証明書検証エラーになりました。

送信前にRequestsの `merge_environment_settings()` を呼び、CA・プロキシ・セッションのTLS設定を反映するよう修正しました。証明書検証は有効のままです。CA、プロキシ、クライアント証明書、`trust_env=False`、既定の証明書検証を回帰試験で確認しています。

### 作成した試験仕様側：npmの404本文をobjectと決めつけた

npmのバージョン取得APIは、対象がない場合にJSON文字列 `"Not Found"` を返しました。こちらで設定したobject型という期待値が不適切でした。公開資料から確定できない404本文の形式制約を外し、404というstatusを照合します。APIの不具合とは判定していません。

## 再実行

```bash
python docs/run_public_api_checks.py --execute --output-dir .artifacts/public-api
```

通常のpytestやCIでは外部サービスへ自動送信しません。明示実行時だけ、固定した3ホストへGETを12件、1秒以上間隔を空けて順番に送信します。API用の認証環境変数はこのプロセス内で外し、他サービスの資格情報が公開APIへ送られないようにしています。HTTPSのCA・プロキシ設定は維持します。

出力：各サービスのOpenAPI、試験仕様Excel、結果Excel、JUnit XML、実応答・判定・実行日時を含む `evidence.json`。外部サービスの仕様変更や障害によって、後日の結果は変わり得ます。

## 参照資料

- [PyPI JSON API公式資料](https://github.com/pypi/warehouse/blob/main/docs/user/api/json.md)
- [npm Public Registry API](https://github.com/npm/registry/blob/main/docs/REGISTRY-API.md)
- [crates.io API設計](https://github.com/rust-lang/crates.io/blob/main/docs/API-DESIGN.md)
- [crates.io利用方針](https://crates.io/policies)
