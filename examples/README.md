# サンプルファイル集

このツールを使う際に人間が用意するファイルのサンプル。`openapi.json`（対象APIの定義そのもの）
以外は全部オプションで、使う機能に応じて必要なものだけ用意すればよい。

| ファイル | 必須/任意 | 必要になる場面 | 使う場所 |
|---|---|---|---|
| `openapi.json` | 必須 | 常に | 全コマンド共通の引数 |
| `auth_config.json` | 任意 | ログイン方式の認証を使う場合 | `--auth-config` |
| `config.json` | 任意 | `--setup`/`--teardown`、DB検証を使う場合 | `--config` |
| `setup.sql` / `teardown.sql` | 任意 | 試験前後にDBを初期化する場合 | `--setup` / `--teardown` |
| `mapping.yaml` | 任意 | DBシナリオの叩き台を自動生成する場合 | `generate_db_scenarios.py`の第2引数 |
| `scenarios.yaml` | 任意 | DB検証（Layer 2）を行う場合 | `db_scenario_runner.py`の第1引数 |

## auth_config.json

ログインAPIを叩いてトークンを取得する方式の認証を使う場合に用意する。
固定トークンで済む場合（`TEST_AUTH_TOKEN`環境変数）は不要。

```sh
python runner/runner.py 試験仕様.xlsx openapi.json --base-url http://localhost:8080 --auth-config examples/auth_config.json
```

- `login_url`/`method`: 必須。ログインAPIのパスとHTTPメソッド
- `body`: ログインリクエストのJSONボディ
- `token_path`: レスポンスJSON内のトークンの場所（ドット区切り、省略時 `access_token`）
- `header_name`/`header_format`: 付与するヘッダの形式（省略時 `Authorization: Bearer {token}`）

## config.json

PostgreSQL/InfluxDBへの接続情報。`--setup`/`--teardown`やDB検証を使う場合に用意する。
実際に使うエンジンのセクションだけあればよい（`postgres`のみ、`influxdb`のみでも可）。

```sh
python runner/runner.py 試験仕様.xlsx openapi.json --base-url http://localhost:8080 \
  --setup examples/setup.sql --teardown examples/teardown.sql --config examples/config.json
```

## setup.sql / teardown.sql

試験前後にDBへ流す素のSQL。`setup.sql`は「試験に関係ないデータの削除＋ID指定系試験
（GET/PUT/DELETE）が404にならないためのダミーデータ投入」、`teardown.sql`は
「試験で作ったデータの後片付け」という役割分担が基本。

## mapping.yaml

DBシナリオYAMLの叩き台を自動生成するための、operationId→テーブル/measurementの対応表。

```sh
python runner/generate_db_scenarios.py openapi.json examples/mapping.yaml -o scenarios.generated.yaml
```

生成された`scenarios.generated.yaml`は必ず中身を確認・修正すること（詳細は `runner/README.md`）。

## scenarios.yaml

DB検証（Layer 2）のシナリオ定義。手書きするか、`mapping.yaml`から自動生成した叩き台を
修正して作る。`{{response.xxx}}`で直前のAPIレスポンスの値を後続シナリオに引き継げる。

```sh
python runner/db_scenario_runner.py examples/scenarios.yaml openapi.json \
  --base-url http://localhost:8080 --config examples/config.json --dry-run
```

まず`--dry-run`で内容を確認してから、`--dry-run`を外して実行することを推奨する。
