# サンプルファイル集

このツールを使う際に人間が用意するファイルのサンプル一式。**全ファイルが`openapi.json`
（架空の「Example Shop API」）1つに対して一貫して整合するように作ってあり、実際に
すべて動作確認済み。** 断片的な例ではなく、このディレクトリのファイルだけでコマンドを
そのまま試せる。

## Example Shop API について

`openapi.json`はユーザー・注文を扱う架空のAPI。以下のエンドポイントを持つ：

| operationId | メソッド/パス | 内容 |
|---|---|---|
| `login` | POST /login | ログイン（`username`/`password`→トークン） |
| `createUser` | POST /users | ユーザー作成 |
| `getUser`/`updateUser`/`deleteUser` | GET/PUT/DELETE /users/{id} | ユーザーの取得・更新・削除 |
| `createOrder` | POST /orders | 注文作成（`items`配列で複数の注文明細をネストして送る） |
| `getOrder` | GET /orders/{id} | 注文の取得 |
| `postSensorData` | POST /sensor-data | センサーデータ送信（InfluxDB検証用） |

DB側は`users`・`orders`・`order_lines`（注文明細、`orders`への外部キーを持つ子テーブル）の
3テーブル構成（`setup.sql`参照）。`postSensorData`だけInfluxDB（`sensor_data`measurement）。

## ファイル一覧

| ファイル | 必須/任意 | 必要になる場面 | 使う場所 |
|---|---|---|---|
| `openapi.json` | 必須 | 常に | 全コマンド共通の引数 |
| `auth_config.yaml` | 任意 | ログイン方式の認証を使う場合 | `--auth-config` |
| `config.json` | 任意 | `--setup`/`--teardown`、DB検証を使う場合 | `--config` |
| `setup.sql` / `teardown.sql` | 任意 | 試験前後にDBを初期化する場合 | `--setup` / `--teardown` |
| `mapping.yaml` | 任意 | DBシナリオの叩き台を自動生成する場合 | `generate_db_scenarios.py`の第2引数 |
| `scenarios.yaml` | 任意 | DB検証（Layer 2）を行う場合 | `db_scenario_runner.py`の第1引数 |

## 実際に試してみる

Layer 1（インターフェース試験）:

```sh
python src/cli.py examples/openapi.json -o cases.json --excel-output spec.xlsx
python runner/runner.py spec.xlsx examples/openapi.json --base-url http://localhost:8080 \
  --setup examples/setup.sql --teardown examples/teardown.sql --config examples/config.json \
  --auth-config examples/auth_config.yaml --dry-run
```

Layer 2（DB検証）:

```sh
python runner/db_scenario_runner.py examples/scenarios.yaml examples/openapi.json \
  --base-url http://localhost:8080 --config examples/config.json \
  --auth-config examples/auth_config.yaml --dry-run
```

`--base-url`を実際に動いているサーバーに向け、`--dry-run`を外せば本当に実行できる
（`examples/openapi.json`通りのAPIを自分で実装すれば、そのまま最初から最後まで動く）。

## auth_config.yaml

ログインAPIを叩いてトークンを取得する方式の認証を使う場合に用意する。
固定トークンで済む場合（`TEST_AUTH_TOKEN`環境変数）は不要。

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
python runner/generate_db_scenarios.py examples/openapi.json examples/mapping.yaml -o scenarios.generated.yaml
```

生成された`scenarios.generated.yaml`は必ず中身を確認・修正すること（詳細は `runner/README.md`）。
`order_lines`（`orders`への外部キーを持つ子テーブル）は自動生成では対応できないため、
`mapping.yaml`のコメントと`examples/scenarios.yaml`の該当シナリオを参照。

## scenarios.yaml

DB検証（Layer 2）のシナリオ定義。手書きするか、`mapping.yaml`から自動生成した叩き台を
修正して作る。全7シナリオで、以下を実例として示している：

- **複数カラムの確認**: `createUser`（name+email）、`createOrder`（user_id+status）— `columns`は
  辞書なので何個でも列挙できる
- **親子テーブル・外部キーの確認**: `createOrder`実行後、`orders`テーブルとは別に
  `order_lines`テーブルも確認するシナリオ（`order_id`の外部キーで紐づく子テーブル）
- **シナリオ間の値の引き継ぎ**: `updateUser`/`deleteUser`は、直前の`createUser`シナリオの
  レスポンスIDを`path_params`で受け取っている。`{{response.xxx}}`は`where`/`columns`等の
  DB検証側だけでなく、APIリクエスト側（`path_params`/`body`）でも使える。ただし常に
  **直前の1シナリオ**のレスポンスを参照する点に注意（2つ前より前は参照できない）
- **削除の確認**: `deleteUser`後に`expect.exists: false`で行が消えたことを確認
- **InfluxDBの確認**: `postSensorData`は`defaults`のpostgresを`db_check.engine`で明示的に上書き
- **response_check（APIレスポンス自体の確認）**: `db_check`は「API呼び出し**後**のDB変化」しか
  見られないため、「DBに事前に仕込んだ値をGET系APIが正しく返すか」という逆方向の確認には使えない。
  `examples/setup.sql`で`id=999`に高額商品（99999999.99）をあらかじめ仕込んでおき、
  `getOrder`シナリオで`response_check`を使ってレスポンスの中身（`items.0.price`のような
  配列要素も含む）を直接検証している

```sh
python runner/db_scenario_runner.py examples/scenarios.yaml examples/openapi.json \
  --base-url http://localhost:8080 --config examples/config.json --dry-run
```

まず`--dry-run`で内容を確認してから、`--dry-run`を外して実行することを推奨する。

**分量について**: `scenarios.defaults`に共通の値（`engine`）をまとめて指定できる。
同じ値をシナリオごとに繰り返し書く必要がなくなり、可読性を落とさずに分量を抑えられる。
`db_check`側で明示すれば個別に上書きも可能。
