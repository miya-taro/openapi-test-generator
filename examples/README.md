# サンプルファイル集

このツールを使う際に人間が用意するファイルのサンプル。`openapi.json`（対象APIの定義そのもの）
以外は全部オプションで、使う機能に応じて必要なものだけ用意すればよい。

| ファイル | 必須/任意 | 必要になる場面 | 使う場所 |
|---|---|---|---|
| `openapi.json` | 必須 | 常に | 全コマンド共通の引数 |
| `auth_config.yaml` | 任意 | ログイン方式の認証を使う場合 | `--auth-config` |
| `config.json` | 任意 | `--setup`/`--teardown`、DB検証を使う場合 | `--config` |
| `setup.sql` / `teardown.sql` | 任意 | 試験前後にDBを初期化する場合 | `--setup` / `--teardown` |
| `mapping.yaml` | 任意 | DBシナリオの叩き台を自動生成する場合 | `generate_db_scenarios.py`の第2引数 |
| `scenarios.yaml` | 任意 | DB検証（Layer 2）を行う場合 | `db_scenario_runner.py`の第1引数 |

## auth_config.yaml

ログインAPIを叩いてトークンを取得する方式の認証を使う場合に用意する。
固定トークンで済む場合（`TEST_AUTH_TOKEN`環境変数）は不要。

```sh
python runner/runner.py 試験仕様.xlsx openapi.json --base-url http://localhost:8080 --auth-config examples/auth_config.yaml
```

- `login_url`/`method`: 必須。ログインAPIのパスとHTTPメソッド
- `body`: ログインリクエストのJSONボディ
- `token_path`: レスポンスJSON内のトークンの場所（ドット区切り、省略時 `access_token`）
- `header_name`/`header_format`: 付与するヘッダの形式（省略時 `Authorization: Bearer {token}`）

JSON形式（拡張子`.json`）でも動作するが、`examples/auth_config.yaml`はYAML形式で用意している。
理由は、`token_path`や`header_format`の書き方には複数のパターン（トークンがネストしたJSON内にある、
ヘッダがBearer形式でなくAPIキー形式、等）があり、YAMLならコメントとして全パターンを
残しておいて、使うものだけコメントを外す、という書き方ができるため。実際に使うAPIの
レスポンス形式に合わせて`examples/auth_config.yaml`内のコメントを参照して選ぶこと。

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

**複数テーブルにまたがる場合**: 1本のSQLファイルの中に文を並べて書けばよい。ただし
外部キーの関係がある場合、TRUNCATEは子テーブル（外部キーで参照する側）から先に、
INSERTは親テーブル（参照される側）から先に行うこと。`examples/setup.sql`は
`users`→`orders`→`order_lines`という親子関係を例に示している。

**重要な制限**: `--setup`/`--teardown`はPostgreSQLにのみ対応している（実行はSQLファイルを
psycopg2で流すだけの単純な仕組みのため）。InfluxDBはSQLではなくLine Protocolでデータを
書き込むため、この仕組みでは初期データを仕込めない。InfluxDBの試験データが必要な場合は、
別途スクリプトを用意するか、試験対象のAPI経由でデータを作成する必要がある。

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

**分量について**: シナリオ数が増えると素直にYAMLも長くなる（1操作あたり10〜15行程度）。
構造をこれ以上圧縮する余地は小さいため、「本当にDB整合性が心配な操作だけ書く」という
運用で分量を抑えるのが現実的。参照系（GET）や、副作用のない単純な操作は対象外にしてよい。
