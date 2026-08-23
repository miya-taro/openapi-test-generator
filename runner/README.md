# openapi-test-run

OpenAPI テスト仕様 Excel を読み込み、実際の API サーバーに対して HTTP リクエストを送信し、結果を Excel に書き出す自動試験ランナー。

## 前提

- Python 3.10+
- `curl.exe`（Windows 標準 curl）が PATH に存在すること
- 試験項目 Excel は `openapi-test-gen` で生成したもの（`test_spec` シート）

## セットアップ

依存関係はリポジトリルートの `requirements.txt` に統合されている（`openapi-test-gen` と共通）。

```sh
# リポジトリルートで実行
pip install -r requirements.txt
```

## 使い方

```sh
python runner.py <excel_path> <openapi_path> --base-url <url> [オプション]
```

### 引数

| 引数 | 必須 | 説明 |
|---|---|---|
| `excel_path` | ✓ | 試験項目 Excel ファイルのパス |
| `openapi_path` | ✓ | openapi.json のパス（baseline 自動生成に使用）|
| `--base-url` | ✓ | API サーバーのベース URL（例: `http://192.168.1.100:8080`）|
| `--output` | | 結果 Excel の出力先（省略時: `{元ファイル名}_result.xlsx`）|
| `--health-path` | | ヘルスチェック用パス（省略時: `/health`）|
| `--fail-fast` | | Level 1 NG が出た時点で実行を停止する |
| `--dry-run` | | HTTP リクエストを送信せずに終了する |
| `--full-body` | | 実測ボディを 21 文字で切り捨てずに全文出力する |
| `--setup` | | 試験実行前に実行する SQL ファイルのパス |
| `--teardown` | | 試験実行後に実行する SQL ファイルのパス（失敗しても続行）|
| `--config` | | DB 接続情報の設定ファイル（`--setup` / `--teardown` 指定時は必須）|
| `--auth-config` | | ログインして認証トークンを取得するための設定ファイル（下記「ログインして認証する API」参照）|

### 環境変数

| 変数名 | 説明 |
|---|---|
| `TEST_AUTH_TOKEN` | Bearer トークン（設定時は `Authorization: Bearer {TOKEN}` ヘッダを付与）。固定トークンをそのまま使える場合はこちら |
| `TEST_AUTH_HEADER_NAME` / `TEST_AUTH_HEADER_VALUE` | 付与するヘッダ名・ヘッダ値を直接指定する（`--auth-config` 指定時は実行時に自動設定される）|

`case.param_in == "header"` の試験ケース（Authorization ヘッダ自体を試験対象とするケース）では、この自動付与は行われない（試験ケース側の値が優先される）。

## 使用例

### 動作確認（dry-run）

```sh
python runner.py tests/fixtures/sample.xlsx openapi.json --base-url http://localhost:8080 --dry-run
```

### 実際に試験を実行する

```sh
python runner.py 試験項目.xlsx openapi.json --base-url http://192.168.1.100:8080
```

結果は `試験項目_result.xlsx` に書き出される。

### 認証が必要な API

固定トークンがあらかじめ分かっている場合:

```sh
$env:TEST_AUTH_TOKEN = "your-token-here"
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080
```

### ログインして認証する API

ログインAPIを叩いてトークンを発行する方式の場合は `--auth-config` を使う。ヘルスチェックの直後・試験実行前に
1回だけログインを行い、取得したトークンを以降の全リクエストに自動で付与する。

`auth.json` の例:

```json
{
  "login_url": "/login",
  "method": "POST",
  "body": { "username": "test-user", "password": "test-pass" },
  "token_path": "access_token",
  "header_name": "Authorization",
  "header_format": "Bearer {token}"
}
```

| キー | 必須 | 説明 |
|---|---|---|
| `login_url` | ✓ | ログインAPIのパス（`--base-url` からの相対パス）|
| `method` | ✓ | HTTPメソッド（通常 `POST`）|
| `body` | | ログインリクエストのJSONボディ |
| `token_path` | | レスポンスJSON内のトークンの場所。ドット区切り（例: `data.token`）。省略時 `access_token` |
| `header_name` | | 付与するヘッダ名。省略時 `Authorization` |
| `header_format` | | トークンの埋め込み方。`{token}` がトークン文字列に置換される。省略時 `Bearer {token}` |

```sh
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080 --auth-config auth.json
```

DBシナリオランナー（`db_scenario_runner.py`）でも同じ `--auth-config` オプションが使える。

### 出力先を指定する

```sh
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080 --output results/run1.xlsx
```

## setup / teardown hooks

試験実行前後に SQL ファイルを実行して DB を初期化・クリーンアップできます。

### config.json のフォーマット

`postgres` セクションが `--setup`/`--teardown` フックで使われる。`influxdb` セクションは
[db_scenario_runner.py](#dbシナリオによるdb検証) で InfluxDB を検証対象にする場合のみ必要。

```json
{
  "postgres": {
    "host": "192.168.1.100",
    "port": 5432,
    "dbname": "mydb",
    "user": "testuser",
    "password": "testpass"
  },
  "influxdb": {
    "host": "192.168.1.100",
    "port": 8086,
    "database": "metrics",
    "username": "testuser",
    "password": "testpass"
  }
}
```

### setup.sql / teardown.sql のサンプル

```sql
-- setup.sql: テストデータを初期化する
TRUNCATE users RESTART IDENTITY CASCADE;
INSERT INTO users (name, email) VALUES ('テストユーザー', 'test@example.com');
```

```sql
-- teardown.sql: テストデータをクリーンアップする
TRUNCATE users RESTART IDENTITY CASCADE;
```

### 使用例

```sh
python runner.py 試験項目.xlsx openapi.json \
  --base-url http://192.168.1.100:8080 \
  --setup setup.sql \
  --teardown teardown.sql \
  --config config.json
```

### 動作仕様

- **setup**: SQL エラー / DB 接続失敗 → エラーメッセージを表示して終了コード 3 で即時終了
- **teardown**: SQL エラー / DB 接続失敗 → 警告ログのみで続行（試験結果に関わらず必ず実行）
- `--setup` または `--teardown` を指定する場合は `--config` が必須（なければ終了コード 4）

---

## 終了コード

| コード | 意味 |
|---|---|
| 0 | 全ケース OK |
| 1 | 1 件以上 NG（ステータス不一致 / Content-Type 不一致）|
| 2 | 1 件以上 Warning（応答時間超過）|
| 3 | 実行エラー（接続失敗 / Excel 読み込み失敗 / setup SQL エラー）|
| 4 | 設定エラー（--setup / --teardown に --config が指定されていない）|

## 結果 Excel の列（P〜U 列）

| 列 | ヘッダ | 内容 |
|---|---|---|
| P | 実行日時 | ISO 8601 形式 |
| Q | 実測ステータス | 実際のHTTPステータスコード |
| R | 実測ヘッダ | レスポンスヘッダ |
| S | 実測ボディ | レスポンスボディ（21 文字超は短縮）|
| T | 応答時間(ms) | レスポンスタイム |
| U | 判定詳細 | NG・Warning の理由 |

## 検証ロジック

- **Level 1（必須）**: HTTP ステータスコードが期待値と一致するか
- **Level 2**: 応答時間が期待値（`期待応答時間` 列）以内か（超過は Warning）
- **Level 3**: Content-Type ヘッダが期待値と前方一致するか（不一致は NG）
- **Level 4**: レスポンスボディが `openapi.json` の該当ステータスのレスポンススキーマ
  （`responses.{status}.content.application/json.schema`）に適合するか（`jsonschema` で検証。不一致は NG）
  該当ステータスにスキーマが定義されていない場合は検証をスキップする。

Level 1 が NG の場合、Level 2〜4 は評価しない。

---

## DBシナリオによるDB検証

`runner.py`（Excel の試験項目を実行するツール）とは別レイヤの、業務シナリオ観点のツール。
「APIを呼び出した結果、DB（PostgreSQL / InfluxDB）が期待通り変化したか」をYAMLで宣言的に記述して検証する。

試験データの初期化・後始末はこのツールの範囲外。上記の `--setup`/`--teardown`（TRUNCATE等）を
使って、シナリオ実行の前後でテーブルを初期化する運用を想定している。

### シナリオ定義（YAML）

```yaml
scenarios:
  - name: ユーザー作成でusersテーブルに1行増える
    request:
      operationId: createUser
      body: { name: "太郎", email: "taro@example.com" }
    db_check:
      engine: postgres
      table: users
      where: { email: "taro@example.com" }
      expect:
        exists: true
        columns: { name: "太郎" }

  - name: 作成したユーザーを更新する（前のシナリオのレスポンスから id を引き継ぐ）
    request:
      operationId: updateUser
      path_params: { id: "{{response.id}}" }
      body: { name: "次郎" }
    db_check:
      engine: postgres
      table: users
      where: { id: "{{response.id}}" }
      expect:
        columns: { name: "次郎" }

  - name: センサーデータ送信でInfluxDBにポイントが書き込まれる
    request:
      operationId: postSensorData
      body: { device_id: "abc123", temperature: 23.5 }
    db_check:
      engine: influxdb
      measurement: sensor_data
      tags: { device_id: "abc123" }
      time_range: 5m
      expect:
        exists: true
        fields: { temperature: 23.5 }
```

- `where`/`tags`/`columns`/`fields` の値に `{{response.xxx}}` と書くと、直前のAPIレスポンスJSONの値
  （作成されたIDなど）に置き換わる（ネストしたパスは `{{response.user.id}}` のようにドット区切り）
- `table`/`where`/`columns`（PostgreSQL）、`measurement`/`tags`/`fields`（InfluxDB）を指定するだけで
  SQL/InfluxQLを書かずに検証できる。JOINや集計など複雑な検証が必要な場合のみ、PostgreSQL側で
  `raw_sql` を直接指定するエスケープハッチがある
- `expect.exists: false` で「行/ポイントが存在しないこと」も検証できる（削除シナリオ用）

### 使用例

```sh
python db_scenario_runner.py scenarios.yaml openapi.json \
  --base-url http://192.168.1.100:8080 \
  --config config.json \
  --auth-config auth.json
```

`config.json` は `--setup`/`--teardown` と同じファイルを使う。`postgres` シナリオのみなら
`influxdb` セクションは不要、逆も同様（実際に使うエンジンのセクションのみ検証される）。

`--auth-config` はオプションで、フォーマットは `runner.py` と共通（「ログインして認証する API」参照）。
指定するとログインして取得したトークンが、シナリオ実行時の全APIリクエストに自動で付与される。

`--dry-run` を付けると、シナリオYAML/openapi.json/config.jsonの読み込みと件数確認だけを行い、
実際のAPIリクエスト送信・DB接続は一切行わずに終了する（`runner.py`の`--dry-run`と同じ考え方）。
DB検証は実際にデータを書き込む操作を伴うことが多いため、初めて設定を試すときはまず
`--dry-run`で内容を確認してから本実行することを推奨する。

### 終了コード

| コード | 意味 |
|---|---|
| 0 | 全シナリオOK |
| 1 | 1件以上NG（該当データなし / カラム値不一致 / operationId不明 等）|
| 3 | 実行エラー（ファイル不在 / YAML不正 / DB接続失敗 / ヘルスチェック失敗）|

### シナリオYAMLの叩き台を自動生成する

シナリオYAMLを白紙から書くのは大変なため、`openapi.json` と「operationId → テーブル名」の
簡単な対応表から、叩き台を自動生成できる。POST/PUT/PATCH/DELETE（データを変更する操作）を
自動で拾い出し、リクエストボディはスキーマから有効な値を自動で埋める。

対応表（`mapping.yaml`）:

```yaml
operations:
  createUser:
    engine: postgres
    table: users
  postSensorData:
    engine: influxdb
    measurement: sensor_data
    tags: [device_id]   # タグとして扱うフィールド（influxdbのみ）
```

```sh
python generate_db_scenarios.py openapi.json mapping.yaml -o scenarios.generated.yaml
```

生成されるYAMLの `where`/`columns`/`fields` は、送信したリクエストボディと同じ値で
「そのデータが本当にDBに存在するか」を検証する形になる。ただし以下は自動では判断できないため、
生成後に必ず確認・修正すること。

- `id` のようなサーバー側で自動採番されるフィールドは `where` から除外される（送信値と一致しない可能性が高いため）
- ネストしたオブジェクト・配列（別テーブルへのリレーションの可能性がある）も `where` から除外される
- `update`/`delete` 系の `path_params` は `{{response.id}}` のプレースホルダになる。実際に使うには、
  対象データを作成する `create` 系シナリオを先に置き、そのレスポンスから値を引き継ぐ想定で
  シナリオの順序を調整する必要がある

## テスト

```sh
python -m pytest tests/ -q
```

## ディレクトリ構成

```
runner/
├── runner.py           # CLI エントリーポイント
├── models.py           # RunCase / RunResult / ResponseSchema
├── excel_reader.py     # 試験項目 Excel → RunCase[]
├── request_builder.py  # RunCase → curl 引数・URL
├── http_client.py      # subprocess + curl.exe 実行
├── response_schema.py  # RunCase → ResponseSchema 変換
├── verifier.py         # Level 1〜4 検証
├── response_validator.py  # Level 4: レスポンスボディの JSON Schema 検証
├── excel_writer.py     # 結果 Excel 書き込み（P〜U 列）
├── config_loader.py     # config.json（postgres/influxdb セクション）読み込み
├── hook_runner.py       # --setup/--teardown SQL 実行
├── db_scenario_runner.py  # DBシナリオ CLI エントリーポイント
├── db_scenario.py       # DBシナリオ YAML 読み込み・プレースホルダ解決
├── db_backends/
│   ├── postgres_backend.py  # engine: postgres の検証
│   └── influx_backend.py    # engine: influxdb の検証
└── tests/
    ├── fixtures/
    │   └── sample.xlsx
    ├── test_excel_reader.py
    ├── test_request_builder.py
    ├── test_http_client.py
    ├── test_http_client_integration.py
    ├── test_response_schema.py
    ├── test_verifier.py
    ├── test_excel_writer.py
    └── test_runner_e2e.py
```
