# openapi-test-run

OpenAPI テスト仕様 Excel を読み込み、実際の API サーバーに対して HTTP リクエストを送信し、結果を Excel に書き出す自動試験ランナー。

## 前提

- Python 3.10+
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
| `--parallel N` | | 同時実行数（省略時: 1=順次実行）。各ケースは互いに独立しているため並列化できる。`--fail-fast` との併用時、既に実行中のケースは完了まで走るため停止タイミングは概算になる |
| `--dry-run` | | HTTP リクエストを送信せずに終了する |
| `--full-body` | | 実測ボディを 21 文字で切り捨てずに全文出力する |
| `--setup` | | 試験実行前に実行する SQL ファイルのパス |
| `--teardown` | | 試験実行後に実行する SQL ファイルのパス（失敗しても続行）|
| `--config` | | DB 接続情報の設定ファイル（`--setup` / `--teardown` 指定時は必須）|
| `--auth-config` | | ログインして認証トークンを取得するための設定ファイル（下記「ログインして認証する API」参照）|
| `--cookie-jar` | | セッションCookieを実行全体で自動的に維持する。ログインでセットされたセッションCookie等が以降の全リクエストに自動で送信される。`--parallel` と同時指定不可 |
| `--junit-xml` | | 結果 Excel に加えて、同じ実行結果を JUnit XML 形式でも出力する（CIダッシュボード連携用）|

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

`auth_config.yaml` の例（JSON形式でも動作するが、YAMLならコメントで書き方の
バリエーションを残せるためYAML形式を推奨。サンプル: [`examples/auth_config.yaml`](../examples/auth_config.yaml)）:

```yaml
login_url: /login
method: POST
body:
  username: test-user
  password: test-pass
# token_path: data.token          # レスポンスがネストしている場合のみ指定
# header_name: X-Api-Key          # Authorization以外のヘッダを使う場合のみ指定
# header_format: "{token}"        # Bearer形式でない場合のみ指定
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
python runner.py 試験項目.xlsx openapi.json --base-url http://localhost:8080 --auth-config auth_config.yaml
```

DBシナリオランナー（`db_scenario_runner.py`）でも同じ `--auth-config` オプションが使える。

#### DBシナリオで役割別アカウントを使う

権限や所有者の違いを同じ実行内で試す場合は、共通のログイン先に対する名前付きプロファイルを指定できます。`auth_profiles` はプロファイル名からログインボディへの対応で、認証情報を含むためプロジェクト設定や試験ケースには保存せず、GUIでは実行時に入力します。

```json
{
  "login_url": "/login",
  "method": "POST",
  "auth_profiles": {
    "read_only": {"username": "test-reader", "password": "..."},
    "support": {"username": "test-support", "password": "..."}
  }
}
```

DBシナリオでは `auth_profile` で使用するログイン情報を選びます。項目がないシナリオは通常の `body`（GUIの基本ログインボディ）を使います。名前付きプロファイルはログイン先・token設定を共通利用し、セッションCookieはプロファイルごとに分離されます。

```yaml
- name: 閲覧者が他ユーザー所有の注文を変更できない
  auth_profile: read_only
  given:
    - table: users
      as: other_user
      fields: {email: "other@example.test"}
    - table: orders
      as: other_order
      fields: {user_id: "{{given.other_user.id}}", status: "pending"}
  request:
    operationId: updateOrder
    path_params: {id: "{{given.other_order.id}}"}
    body: {status: "cancelled"}
  response_check:
    expect: {status: 403}
  db_check:
    engine: postgres
    table: orders
    where: {id: "{{given.other_order.id}}"}
    expect: {exists: true, columns: {status: "pending"}}
```

`auth_profile` の名前は GUI の「役割別ログイン情報」と一致させます。期待する拒否ステータスはAPI実装・OpenAPIに基づき、403または404をレビューして選んでください。ログインには試験用アカウントを使い、`given` には他人所有の試験データだけを作成してください。各 `given` はシナリオ後に逆順で削除されます。

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

テーブル全体のTRUNCATE等、試験実行全体を通した初期化・後始末は `db_scenario_runner.py` 自身の
範囲外（下記 `--setup`/`--teardown` を使う）。一方、個々のシナリオが必要とする前提データ
（`given`）は本ツール自身が用意・後始末する（下記参照）。

- **GUIを使う場合**: 「DB準備」タブ④でsetup.sql/teardown.sqlを生成し、その場の
  「実行（DBに反映）」ボタンで直接DBへ反映するのが基本の流れ。自動生成された内容を
  プレビューでレビューしてから反映できるため、こちらを推奨する。
- **CLIを直接使う場合**: 上記の `--setup`/`--teardown`（`runner.py`のオプション、TRUNCATE等）を
  使って、シナリオ実行の前後でテーブルを初期化する方法もある。ただしこちらは
  レビュー無しでそのままDBに反映される点に注意。

### シナリオ定義（YAML）

```yaml
scenarios:
  defaults:
    engine: postgres   # 個々の db_check で省略した場合の既定値。上書きも可能（下のInfluxDBの例）

  list:
    - name: ユーザー作成でusersテーブルに1行増える
      request:
        operationId: createUser
        body: { name: "太郎", email: "taro@example.com" }
      db_check:
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
        table: users
        where: { id: "{{response.id}}" }
        expect:
          columns: { name: "次郎" }

    - name: センサーデータ送信でInfluxDBにポイントが書き込まれる
      request:
        operationId: postSensorData
        body: { device_id: "abc123", temperature: 23.5 }
      db_check:
        engine: influxdb   # defaults(postgres)と異なるのでここで明示的に上書き
        measurement: sensor_data
        tags: { device_id: "abc123" }
        time_range: 5m
        expect:
          exists: true
          fields: { temperature: 23.5 }
```

- `scenarios.defaults` に書いた値（現状 `engine` のみ対応）は、各シナリオの `db_check` で
  省略した場合の既定値になる。同じ値をシナリオごとに繰り返し書かずに済み、ファイルの分量を
  抑えられる。`db_check` 側で明示すれば上書きできる
- 旧形式（`scenarios:` の直下にシナリオのリストを書き、`db_check.engine` を毎回明示する形）も
  後方互換で引き続き動作する
- `where`/`tags`/`columns`/`fields`（DB検証側）に加え、`request.path_params`/`request.query_params`/`request.body`
  （APIリクエスト側）にも `{{response.xxx}}` と書ける。どちらも**直前のシナリオ**のAPIレスポンス
  JSONの値（作成されたIDなど）に置き換わる（ネストしたパスは `{{response.user.id}}` のように
  ドット区切り）。`request`側は文字通り「直前」（1つ前のシナリオ）のレスポンスを参照する点に注意
  （2つ前より前のレスポンスは参照できない）。1件目のシナリオで参照した場合は解決できずNGになる
- `request.query_params` を使うとGET等のquery parameterを指定できる。`{{given.xxx.column}}` と書けば、
  `given` で投入した行の値を検索条件に使える。空のquery値は送信されない
- GET一覧の期待結果を既存DBから作る場合は、`db_response_check` を使う。DBへ行をINSERTせず、
  `fields` のDB列とレスポンス項目の対応、および `filters` の検索条件からAPI入力値と期待行を作る
- `table`/`where`/`columns`（PostgreSQL）、`measurement`/`tags`/`fields`（InfluxDB）を指定するだけで
  SQL/InfluxQLを書かずに検証できる。JOINや集計など複雑な検証が必要な場合のみ、PostgreSQL側で
  `raw_sql` を直接指定するエスケープハッチがある

### db_response_check（既存DBからGETの期待レスポンスを作る）

GETで期間検索を行う場合、試験用の行を画面やYAMLに手で用意する必要はない。APIパラメータとDB列の比較条件、
レスポンス項目とDB列の対応を一度定義すると、実行時にPostgreSQLを読み取り専用で参照してAPI入力と期待結果を作る。

```yaml
scenarios:
  list:
    - name: 指定期間の予約一覧を返す
      request:
        operationId: listReservations
      response_check:
        expect:
          status: 200
      db_response_check:
        table: reservations
        array_path: data.items
        fields:
          id: id
          startsAt: starts_at
          status: status
        filters:
          - source: query
            parameter: start
            column: starts_at
            operator: ">="
            auto: true
          - source: query
            parameter: end
            column: starts_at
            operator: "<="
            auto: true
```

- `fields` は「レスポンスの項目パス: DB列名」。配列要素内の `startsAt` のようなネストにも対応する。
- `filters` の `source` は `query` または `path`。比較演算子は `=`, `>`, `>=`, `<`, `<=`。
- `format` はOpenAPIのパラメータformat（`date` / `date-time`等）で、GUIからは自動で引き継ぐ。
  `date-time` パラメータにDBのDATE列しかない場合は、時刻やタイムゾーンを推測せず未確認にする。
- `auto: true` の入力値は既存DBの値から自動選択する。開始・終了の両方を同じ列に設定する期間検索では、
  境界の内側・外側を試せる異なる値が4件以上必要。境界値の行がない、条件に一致する行がない、
  または条件が結果を絞り込む証拠がない場合は合格にせず「未確認」（終了コード2）にする。
- 期待レスポンスはDBの検索結果と項目・件数を完全照合し、配列の順番は問わない。`array_path: null` は単一オブジェクト用。
- GET照合はSELECTのみを実行し、DBを書き換えない。ページング、JOIN、集計など、単一テーブルの比較条件だけで
  期待値を表せないAPIはこの方式の対象外。

### given（前提データをDBへ直接投入する。factory）

`{{response.xxx}}` によるシナリオ間チェーンは、前段のシナリオが**APIを叩いて**前提データを
作ることが前提になる。しかし、そもそも作成用のAPIエンドポイントが存在しないリソース
（SSO連携・他サービスからのイベント連携・管理画面経由でしか作られないリソース等）は
この方法では前提データを用意できない。`given` は、そうしたリソースをDBへ直接INSERTして
前提データを用意する仕組み（PostgreSQLのみ対応）。

```yaml
scenarios:
  list:
    - name: 在庫がある商品を注文すると在庫が減る
      given:
        - table: products
          as: product_a               # 後で {{given.product_a.xxx}} として参照する名前
          fields: { name: "商品A", stock: 10, status: "active" }
      request:
        operationId: createOrder
        body: { product_id: "{{given.product_a.id}}", qty: 1 }
      db_check:
        table: products
        where: { id: "{{given.product_a.id}}" }
        expect:
          columns: { stock: 9 }
```

- `fields` で指定しなかった列（NOT NULL かつ DB側デフォルトが無い列）は、実際のテーブル定義
  （型・enum・CHECK制約）から自動的に妥当な値を補って埋める（`db準備`のsetup.sql雛形生成と
  同じ仕組みを使っている）。自動採番列（SERIAL/IDENTITY）は指定しても無視され、DBに採番させる
- INSERTされた行全体（自動採番されたID等を含む）が `{{given.<as名>.<カラム名>}}` で参照できる。
  `request.path_params`/`request.body`、`db_check`の`where`/`columns`等、`{{response.xxx}}`が
  使える場所ならどこでも同様に使える
- 投入した行は、そのシナリオの判定が確定した時点で（成功・失敗を問わず）必ず削除される。
  複数指定した場合は作成順の逆順で削除する（`given[1]`が`given[0]`の行をFKで参照している場合の
  ような依存関係を考慮するため）
- 自動生成できない型（バイナリ列など）や、機械的な既定値では都合が悪い列は `fields` で
  明示的に指定する
- `expect.exists: false` で「行/ポイントが存在しないこと」も検証できる（削除シナリオ用）

### invariants（不変条件の検証。PostgreSQLのみ）

`expect.columns`は「実測値がこの絶対値と一致するか」を検証するが、それだけでは
「在庫は注文数量ぶんだけ正しく減っているか」「在庫は負にならないか」のような、
**値同士の関係**を検証するテストは書きにくい（絶対値を毎回手計算してYAMLに書く必要があり、
たまたま数字が合っていただけの偽陽性も起こりうる）。`invariants`は、`db_check`の対象行の
実測値・前提データ・直前のAPIレスポンスを使った比較式を、関係式のまま検証できる。

```yaml
db_check:
  table: products
  where: { id: "{{given.product_a.id}}" }
  invariants:
    - "{{db.stock}} == {{given.product_a.stock}} - 1"   # 注文数量(1)ぶんだけ減っている
    - "{{db.stock}} >= 0"                                # 在庫は負にならない
```

- `{{db.<カラム名>}}`でSELECTした実測値、`{{given.xxx}}`/`{{response.xxx}}`で前提データ・
  直前のAPIレスポンスの値を式の中に埋め込める
- 対応する演算子は四則演算（`+` `-` `*` `/`）と比較（`==` `!=` `<` `<=` `>` `>=`）のみ。
  それ以外の構文（関数呼び出し・変数参照等）はエラーになる（任意コード実行を防ぐため、
  `eval()`ではなくASTをホワイトリスト方式で評価している）
- `expect`と`invariants`は併用できる（両方満たして初めてそのdb_checkはOKになる）
- PostgreSQLのNUMERIC/DECIMAL列は`float`に変換してから式に埋め込む（`Decimal`と`int`/`float`の
  混在演算はエラーになるため）。`expect.columns`の厳密な10進比較とは目的が異なる点に注意

`given`/`invariants`で書くべき業務ルール自体（スキーマには現れない、そのAPI固有の制約）を
人間が思いつく手助けとして、[docs/copilot_scenario_prompt.md](../docs/copilot_scenario_prompt.md)
にGitHub Copilot Chat向けのシナリオ候補生成プロンプトを用意している。

### response_check（APIレスポンス自体の検証）

`db_check`が「APIを呼んだ**後**にDBがどう変化したか」を見るのに対し、`response_check`は
「APIレスポンスの中身そのもの」を期待値と突き合わせる。典型的な用途は逆方向のテスト：
**DBに事前に仕込んだ値（極端な最大値・最小値など）を、GET系APIが正しく返してくるか**の確認。
`db_check`ではこれができない（API呼び出し後のDB変化を見る仕組みなので、呼び出し前から
DBに存在するデータの読み出し確認には使えない）。

```yaml
scenarios:
  list:
    - name: DBに仕込んだ高額な注文を取得すると正しい金額が返る
      request:
        operationId: getOrder
        path_params: { id: 999 }   # --setup で事前に仕込んでおいたID
      response_check:
        expect:
          status: 200
          body:
            id: 999
            items.0.price: 99999999.99   # ドット区切りで配列要素にも辿れる（items[0].price）
```

- `db_check`・`response_check`は片方だけでも両方でも指定できる（両方指定した場合、両方が
  合格して初めてそのシナリオはOKになる）。どちらも指定しない場合はエラーになる
- `expect.status`: 期待するHTTPステータスコード（省略可）
- `expect.body`: レスポンスJSON内のフィールドと期待値（辞書なので複数指定できる）。
  ネストしたパスはドット区切り（`user.name`）、配列要素は数字（`items.0.price`）で辿れる
- `expect.contains`: 一覧レスポンスの配列に、指定したフィールド値を持つ項目が含まれることを確認する。
  `path: "$"` はレスポンス自体、`path: items` はレスポンス内の `items` 配列を対象にする。
- `{{given.<名前>.<カラム>}}` は `given` でDBに作成した行の値に置き換えられるため、採番IDを固定せずに
  GETレスポンスとDBの値を照合できる

```yaml
response_check:
  expect:
    status: 200
    contains:
      - path: "$"
        fields:
          id: "{{given.user.id}}"
          email: "{{given.user.email}}"
```

### 使用例

```sh
python db_scenario_runner.py scenarios.yaml openapi.json \
  --base-url http://192.168.1.100:8080 \
  --config config.json \
  --auth-config auth_config.yaml
```

`config.json` は `--setup`/`--teardown` と同じファイルを使う。`postgres` シナリオのみなら
`influxdb` セクションは不要、逆も同様（実際に使うエンジンのセクションのみ検証される）。

`--report-output XLSX`（Excelレポート）・`--junit-xml XML`（CIダッシュボード連携用）・
`--cookie-jar`（`runner.py`と同じセッションCookie維持機能）も指定できる。

`--auth-config` はオプションで、フォーマットは `runner.py` と共通（「ログインして認証する API」参照）。
指定するとログインして取得したトークンが、シナリオ実行時の全APIリクエストに自動で付与される。

`--cookie-jar` を付けると、`runner.py` と同様にセッションCookieをシナリオ実行全体で
自動的に維持する。DBシナリオは元々シナリオ間で`{{response.xxx}}`を引き継ぐため常に順次実行であり、
`runner.py`の`--parallel`のような制約はない。

`--dry-run` を付けると、シナリオYAML/openapi.json/config.jsonの読み込みと件数確認だけを行い、
実際のAPIリクエスト送信・DB接続は一切行わずに終了する（`runner.py`の`--dry-run`と同じ考え方）。
DB検証は実際にデータを書き込む操作を伴うことが多いため、初めて設定を試すときはまず
`--dry-run`で内容を確認してから本実行することを推奨する。

### 終了コード

| コード | 意味 |
|---|---|
| 0 | 全シナリオOK |
| 1 | 1件以上NG（該当データなし / カラム値不一致 / operationId不明 等）|
| 2 | 未確認のシナリオ、またはテストデータの後片付けに失敗 |
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

GUIでPOST後の片付けを有効にすると、試験前後のDB行を比較し、指定条件に一致する新規行だけを主キーで削除する。
同じ条件を持つ行が並行して作成されると識別できないため、専用のテストDBで、試験ごとに一意となる値を使うこと。
片付けに失敗した場合は警告を出し、終了コード2を返す。

**シナリオの並び順・`{{response.id}}`の引き継ぎは自動で組み立てられる。**
パス（例: `/orders`, `/orders/{id}`, `/orders/{id}/items`）から「リソースファミリー」を推定し、
ファミリー内は 作成 → 更新 → ネスト作成（例: 注文明細の追加）→ … → 削除（削除は子リソースから先） の
順に並べ、各ファミリーの2件目以降の `path_params` は自動で `{{response.id}}`（直前シナリオのレスポンスから
引き継ぐプレースホルダ）にする。

ファミリー間の順序も、リクエストボディのフィールド名（例: `categoryId` → "category" ファミリーへの
依存）から推測した依存関係に基づいて、依存先が先に来るよう並べる。ただしこれは名前ベースの
ヒューリスティックな推測にすぎないため（例えばフィールド名が一般的でない命名の場合は検出できない）、
生成後は必ず並び順と `{{response.id}}` の参照先が意図通りか確認すること。特に：

- 1つのファミリーに複数のリソースが混在している場合（例: 別々の子テーブルを持つリソースが
  同じパスプレフィックスを共有している場合）は、意図しない順序になることがある
- 依存関係が循環していると判定された場合は解決できず、該当ファミリーは末尾にアルファベット順で
  配置される（標準エラー出力に警告が出る）

**作成直後の読み取り確認（response_check）も自動で挿入される。**
`db_check` は「APIを呼んだ**後**にDBがどう変化したか」しか見られず、「作成したリソースがAPI経由で
正しく読み取れるか」（読み取りパス側のバグ）は検証できない。対応する単一リソース取得API
（例: `GET /widgets/{id}`、path paramをちょうど1つだけ持ち、requestBodyを持たない形のGET）が
存在する場合、作成シナリオの直後に、送信したフィールドがそのまま読み取れるかを`response_check`で
確認するシナリオを自動で挿入する（`db_check`は付かない）。対応するGET APIが無い場合や、
送信フィールド名とレスポンスのフィールド名が一致しない場合は手直しが必要。

### setup.sql / mapping.yaml の叩き台を実DBから自動生成する

上記の `mapping.yaml`（operationId→テーブル名の対応表）や、`--setup`/`--teardown` で使う
setup.sql/teardown.sqlを手書きするのは手間がかかるため、実DB（PostgreSQLのみ対応）に接続して
雛形を自動生成する2つのスクリプトがある。どちらも生成物はあくまで叩き台であり、必ず内容を
確認・修正すること。

**setup.sql/teardown.sqlの雛形生成**（`generate_setup_sql.py`）

外部キー制約を満たすINSERT順序（親→子）とTRUNCATE順序（子→親）を自動計算し、
NOT NULL列には型・enum・単純なCHECK制約（`IN (...)`相当）を踏まえた仮値を入れる。
PRIMARY KEY/外部キー列は全テーブル共通の仮値（`id=1`）で紐付け、1テーブルにつき1行を生成する。

```sh
python generate_setup_sql.py --config config.json --setup-output setup.sql.generated --teardown-output teardown.sql.generated
# 対象を絞る場合: --tables users,orders,order_lines（FK先の親テーブルは自動で追加される）
```

自動生成できるのは「実行してエラーにならない雛形」までで、値の意味（実際にテストで使いたい
データかどうか）は自動化の対象外。単純な `IN (...)` 以外のCHECK制約（範囲制約など）は
自動で満たせないため、該当箇所には `WARNING` コメントが出力される。

**mapping.yamlの叩き台生成**（`generate_mapping.py`）

各operationのリクエストボディのフィールド名と、実DBの各テーブルのカラム名を突き合わせて
（完全一致・スネークケース/キャメルケース変換後の一致・あいまい一致）、最も一致するテーブルを
推定する。名前ベースのヒューリスティックであり精度は100%ではないため、各行に確信度
（高/中/低）を必ずコメントで出力する。「低」は特に人間の判断で修正が必要。

素のPHPの場合は、CopilotにSQL根拠（PHP相対パスと行番号）を含む
`openapi.db-evidence.json`を作らせ、任意で照合に使える。例:

```sh
python generate_mapping.py openapi.json --config config.json \
  --php-db-evidence openapi.db-evidence.json -o mapping.yaml.generated
```

Copilot候補のテーブル・カラムがOpenAPIのoperationIdと接続先PostgreSQLの実スキーマに一致するか確認し、根拠をYAMLコメントに残す。一致しても確信度は「中」で、人がPHPの実行経路と対応表を確認する必要がある。複数候補やスキーマ不一致は自動選択しない。形式は [`docs/php-db-evidence.schema.json`](../docs/php-db-evidence.schema.json)、GUI手順は [`docs/php_openapi_setup.md`](../docs/php_openapi_setup.md) を参照。

```sh
python generate_mapping.py openapi.json --config config.json -o mapping.yaml.generated
```

リクエストボディを持たない操作（DELETE等）は、同一リソースの他operationの推定結果から
補完を試みる（例: `POST /orders` の推定結果を `DELETE /orders/{id}` にも適用）。ただし
ネストしたリソース（例: `/orders/{id}/lines` は`orders`ではなく別リソース`lines`）は
区別されるため、補完対象は同じリソースの操作に限られる。

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
├── request_builder.py  # RunCase → リクエストボディ・URL
├── http_client.py      # requests によるHTTP実行
├── response_schema.py  # RunCase → ResponseSchema 変換
├── verifier.py         # Level 1〜4 検証
├── response_validator.py  # Level 4: レスポンスボディの JSON Schema 検証
├── excel_writer.py     # 結果 Excel 書き込み（P〜U 列）
├── config_loader.py     # config.json（postgres/influxdb セクション）読み込み
├── hook_runner.py       # --setup/--teardown SQL 実行
├── db_scenario_runner.py  # DBシナリオ CLI エントリーポイント
├── db_scenario.py       # DBシナリオ YAML 読み込み・プレースホルダ解決
├── db_factory.py        # given（前提データ）のDB直接INSERT/削除
├── junit_writer.py      # 実行結果のJUnit XML出力
├── db_backends/
│   ├── postgres_backend.py  # engine: postgres の検証
│   ├── influx_backend.py    # engine: influxdb の検証
│   └── invariant_eval.py    # invariants（不変条件）式の安全な評価
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
