# 期待する調査メモ

これは採点時に参照する人手作成の根拠一覧です。Copilotの出力には、この程度に追跡可能な根拠と未確定事項が必要です。

## API操作

| 操作 | URL・メソッドの根拠 | 入力・応答の根拠 |
|---|---|---|
| `GET /api/users` | `php/public/index.php:13-18` が `/api/users` の `GET` を `list_users()` に振り分ける | `php/src/users.php:6-9` が `limit` をクエリから読み、整数1〜100を受け付ける。未指定時は20。`php/src/users.php:12-19` がDB検索結果と指定値をJSON返却し、200を指定する。 |
| `POST /api/users` | `php/public/index.php:13-18` が同じパスの `POST` を `create_user()` に振り分ける | `php/src/users.php:41-49` が `application/json` とJSONオブジェクトを要求する。`php/src/users.php:52-55` と `php/schema.sql:1-5` がname/emailの検証・長さ・必須相当を示す。`php/src/users.php:59-69` がDB登録、重複時409、成功時201と応答項目を示す。 |
| `GET /api/users/{id}` | `php/public/index.php:23-25` の数値パス正規表現がID付きパスをGETハンドラに渡す | `php/src/users.php:22-36` が正の整数検証、DB検索、400/404/200と返却項目を示す。 |

全操作で `php/public/index.php:20,27` が非対応メソッドを405にし、`php/src/http.php:10-13` が `Allow` と共通JSONエラーを返す。

## 共通応答

- `php/src/http.php:2-7` はHTTPステータスを設定し、`Content-Type: application/json; charset=utf-8` とJSON本文を返す。
- エラー本文は `{ "error": { "code": string, "message": string } }`。各エラー分岐のコードと文言は個別に記述される。
- `GET /api/users` の `items` は `id` integer、`name` string、`email` string。`php/src/users.php:15-19` でIDを整数に変換する。
- `GET /api/users/{id}` と作成成功応答も `id`/`name`/`email` を返す。

## 要確認・推測してはいけない事項

- APIの実際のホスト/Base URLはソースにないため、`servers` URLは確定できない。
- 認証処理はサンプルに存在しない。認証方式やSecurity Schemeを追加しない。
- `APP_DSN` などの環境変数はDB接続用であり、APIのURLやAPI認証情報ではない。
- 予期しないDB例外等の500応答は明示的に整形されていない。共通の500本文・スキーマを推測しない。
- `/api/users` と `/api/users/{id}` 以外のルート実装はない。追加操作を作らない。
