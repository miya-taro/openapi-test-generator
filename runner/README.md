# openapi-test-run

OpenAPI テスト仕様 Excel を読み込み、実際の API サーバーに対して HTTP リクエストを送信し、結果を Excel に書き出す自動試験ランナー。

## 前提

- Python 3.10+
- `curl.exe`（Windows 標準 curl）が PATH に存在すること
- 試験項目 Excel は `openapi-test-gen` で生成したもの（`test_spec` シート）

## セットアップ

```sh
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

### 環境変数

| 変数名 | 説明 |
|---|---|
| `TEST_AUTH_TOKEN` | Bearer トークン（設定時は `Authorization: Bearer {TOKEN}` ヘッダを付与）|

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

```sh
$env:TEST_AUTH_TOKEN = "your-token-here"
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080
```

### 出力先を指定する

```sh
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080 --output results/run1.xlsx
```

## setup / teardown hooks

試験実行前後に SQL ファイルを実行して DB を初期化・クリーンアップできます。

### config.json のフォーマット

```json
{
  "db": {
    "host": "192.168.1.100",
    "port": 5432,
    "dbname": "mydb",
    "user": "testuser",
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

Level 1 が NG の場合、Level 2/3 は評価しない。

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
├── verifier.py         # Level 1〜3 検証
├── excel_writer.py     # 結果 Excel 書き込み（P〜U 列）
├── requirements.txt
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
