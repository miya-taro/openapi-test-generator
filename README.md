# openapi-test-gen / openapi-test-run

OpenAPI 3.x 定義ファイルから **インターフェース観点のテスト仕様を自動生成**し、実際の API サーバーに対して **自動試験を実行**するツールセット。

初版は、**UIでAPI仕様とDB対応を入力し、生成された試験を確認して実行するローカルブラウザー版**です。合否判定と結果・証跡保存まで自動実行します。[初版の対応範囲と使い方](docs/first-release.md)を参照してください。以前配布した旧exeは今回の機能を含まないため、下記のclone起動を利用してください。

```
openapi.json
    │
    ▼  openapi-test-gen (Python / src/)
試験仕様 Excel（test_spec シート）
    │
    ▼  openapi-test-run (Python / runner/)
結果 Excel（実測値・判定・実行コマンドを追記）
```

試験生成・実行はPython、UIはJavaScriptで実装しています。

---

## 構成

```
api test generator/
├── src/                  # openapi-test-gen（試験仕様ジェネレーター）
│   ├── cli.py            # CLI エントリーポイント
│   ├── parser.py         # OpenAPI パース（$ref 解決）
│   ├── extractor.py      # パラメータ・ボディフィールド抽出
│   ├── generator/        # テストケース生成ルール
│   │   └── rules/        # common / string / integer / array / object / auth
│   ├── id_assigner.py    # 試験 ID 採番
│   └── renderer/         # JSON / Excel 出力
├── runner/               # openapi-test-run（試験実行ランナー）
│   └── README.md         # ランナー詳細ドキュメント
├── gui-tauri/            # GUI（デスクトップ版とローカルブラウザー版）
├── gui/                  # gui-tauriが呼び出すPython側の検証ロジック（validators.py等）
├── requirements.txt           # 実行・テスト用の依存関係
├── requirements-runtime.txt   # 配布ランタイムの最小実行依存
└── docs/                 # サンプル OpenAPI・出力ファイル
```

---

## WindowsでGUIアプリを起動する

GUIは `gui-tauri/` に一本化している。Tauriデスクトップ版に加え、Windowsではローカルブラウザー版を起動できる。

リポジトリをcloneし、直下の `run-windows.bat` を実行する。Windows版はローカルのPythonサーバーとブラウザーで動作するため、Tauriのexeを生成・実行しない。

初回起動前に必要なのはPython 3.10以降とNode.js 22.12以降。起動スクリプトがPython仮想環境とnpm依存を準備し、GUIをビルドして既定のブラウザーで開く。RustとVisual Studio C++ Build Toolsは不要。初回は依存のダウンロードと画面のビルドに数分かかることがある。以降は変更がない依存の再インストールを省略する。

```text
git clone https://github.com/miya-taro/openapi-test-generator.git
cd openapi-test-generator
run-windows.bat
```

ブラウザー版は `127.0.0.1` のみで待ち受け、設定を外部サービスへ送信しない。API試験リクエストは画面に指定したBase URLへ送信する。参照したファイルはアプリ用データフォルダーに取り込み、結果を開く操作ではファイルをダウンロードする。フォルダー選択で指定した名前の出力先は `%LOCALAPPDATA%\OpenApiTestTool\output\<フォルダー名>` に作成される。起動中はコマンド画面を閉じず、終了するときは `Ctrl+C` を押す。

- 画面は「対象を登録 → 仕様を確認 → 試験を確認 → 実行 → 結果」の5工程で進める
- 登録済みのDB確認設定から、期間境界・項目の組み合わせ・優先順位・0件時のケースをUIで生成できます。専用テストDBのデータ準備と片付け、期待結果の入力方法は[共通ルール試験](docs/common-rule-tests.md)を参照してください。
- 「DB確認」ではGETの返却項目とDB列、POST・PUT・PATCH・DELETEの保存先と対象行を設定できる。PostgreSQLのPOSTはリクエスト項目の値か、レスポンスで返る採番IDで作成行を特定する。InfluxDBは固定時刻と全タグで単一ポイントを特定する
- DBの対応設定は「APIを選ぶ → 送信値を入力 → DBとの関係を設定 → 試験内容を確認」の順で入力できる。戻っても値を保持し、一覧編集にも切り替えられる。詳しくは[DB設定の手順](docs/db-setup-guide.md)を参照
- GETのJSONボディは「DB確認」で項目ごとに送信値・DB列・比較条件を設定できる。`OR`グループ、期間の`>=`/`<=`、文字列配列の`IN`にも対応する。レスポンス内の配列は配列パスを指定してDB行と照合する
- GETの「条件付き必須とIN配列の正常な組み合わせを生成する」を選ぶと、人が入力した値から拠点の片方ずつ／両方、期間あり／なし、IN配列の全指定／1項目ずつを展開する（最大64件）。試験に必要な入力値は推測しない。各条件の省略を検出できるDB行、期間の端点、INの各指定値に一致するDB行がない場合は「未確認」にする
- DB照合と同じレスポンスについて、契約試験と共通の検証処理でOpenAPIの型・必須項目・日時形式・Content-Type・レスポンスヘッダも検証する。DBとの値の比較は対応付けした項目が対象
- GETの「レスポンス項目の値の照合」で、配列外の項目などを実際の送信値・固定値と比較できる。入力を省略したときの期待値も人が設定する。日時は同じ時刻ならタイムゾーン表記が違っても一致する
- リクエストbodyの「どちらか必須」「両方指定または両方省略」は契約UIで設定でき、それぞれの有効・無効な組み合わせを試験ケースとして生成する。補正後のOpenAPIには `x-otg-presence-rules` として保存する

- 「項目間の大小条件」で `start <= end` などを明示し、大小・同値の正常／異常ケースを生成できる。数値・日時の2項目に対応
- 「DBに変更がないこと」で、明示した範囲・列をAPI実行前後に比較できる。GET・POST・PUT・PATCH・DELETEに対応し、エラー応答でも行の追加・削除・値の変更を検出する。設定手順と制限は [項目間条件・DB変更なし確認](docs/comparison-and-side-effects.md)
- 契約編集でDB比較範囲を設定すると、自動生成する異常系へDB変更なし確認を一括適用できる。試験準備時には、仕様の未対応・未生成・一部対応もUIと証跡に表示する。[合成制約・対応状況・異常系DB比較](docs/contract-reliability.md)
- 型・enum各値・数値境界・分岐の生成漏れと誤判定は、不具合を仕込んだAPIを含めて回帰検証しています。正常側／異常側など観点ごとの未生成項目も表示します。[試験項目の検証範囲と残る制限](docs/contract-coverage-validation.md)

条件付き必須はリクエストbodyのschemaに次のように保存される。既存のOpenAPIに同じ拡張を書いても、UIと同じケースを生成する。

```json
"x-otg-presence-rules": [
  {"kind": "atLeastOne", "fields": ["site_id", "location_id"]},
  {"kind": "together", "fields": ["start", "end"]}
]
```

OpenAPIに `anyOf: [{"required":["site_id"]},{"required":["location_id"]}]` と書いた場合も「どちらか必須」のケースを生成する。OpenAPI 3.1の `dependentRequired: {"start":["end"],"end":["start"]}` からは「両方指定または両方省略」のケースを生成する。

対応DBはPostgreSQLとInfluxDB 1.x（InfluxQL）です。InfluxDBのGET全ポイント照合・単一ポイントの保存／更新／削除・異常系のDB変更なし確認はUIで設定できます。[InfluxDBの設定・検証結果・制限](docs/influxdb-testing.md)

InfluxDBの変更確認では「検証用ポイントを毎回準備し、試験後に削除する」を選び、初期フィールドの名前・型・値を入力すると、同じ設定で繰り返し試験できます。指定時刻・全タグに既存ポイントがある場合は上書きせず停止します。後片付け失敗は結果と証跡に残ります。

location_idから別DBのsite_idを取得し、計測値を照合する設定もUIで作れます。[別DB参照の設定例・0件時の扱い・制限](docs/cross-db-lookup.md)

測定結果検索の具体的な画面設定・試験範囲・実API検証手順は [GET JSONボディの測定結果検索](docs/measure-get-testing.md) を参照。
- 通常入力は `openapi.json`、Base URL、出力先だけ。認証・DB・並列実行は「詳細設定」から必要な場合だけ開く
- 契約試験とDBシナリオ試験は同じ統一ワークフローで実行され、実行ごとのフォルダに試験仕様Excel、結果Excel、JUnit XML、JSONをまとめて出力する。DB試験は `db-scenario-evidence.json` に対応設定・期待値・実測値・判定も保存する（認証情報に該当する項目はマスクする）
- Layer 1/Layer 2とも、最初はケースと試験仕様Excelを準備するだけでAPI・DBへ接続しない。GUIで入力・期待結果・出典を確認し、ケース単位で「レビュー済み」→「承認」にできる
- 承認済みケースは承認実行ボタンから実行する。未承認ケースの実行は別の「予備実行」ボタンで明示し、HTML結果にも未承認の探索実行として記録する。CLIでも準備後に承認状態を検査し、未承認は `--allow-draft` を付けない限り止める
- ケース定義またはOpenAPI/シナリオYAMLが準備後に変わった場合、以前の承認状態を流用せず再準備を要求する
- 承認した内容と実際に実行するExcelのずれを防ぐため、準備後に試験仕様Excelまたは実行Excelを直接編集した場合も実行を止める。内容を修正するときはOpenAPIまたはシナリオYAMLを直して再準備する
- 既存試験IDを保ったケースマスター、試験仕様Excel、結果Excel、JUnit XML、HTMLレポート、失敗ケースID一覧を同じ実行フォルダに出力する。Layer 2のシナリオIDはExcel/JUnit/HTMLでも共通
- 「このPCに設定を保存」で保存した接続先・対象API・実行設定を次回起動時に復元する。DBパスワードと認証用入力は再確認する。[保存・更新・ライセンス](docs/operation-and-licenses.md)
- 実行中は進捗バーで完了件数がリアルタイムに分かる

### 探索的API試験（任意）

Schemathesisを追加すると、「テスト生成・実行」画面の折りたたみ欄からOpenAPIベースの探索試験をローカル実行できます。利用するPython環境に一度だけ追加します。

```powershell
python -m pip install -r docs/requirements-schemathesis.txt
```

既定では選択中のGET操作だけを対象にし、API操作ごとに最大10例、同時実行1、毎秒5リクエスト以下で実行します。認証設定を使う場合はtoken取得のためログインAPIへPOSTします。OpenAPIに認証定義があれば認証あり・なし・不正認証を試して拒否を確認します。Coverageが試す仕様外メソッドは既定で無効です。POST/PUT/PATCH/DELETEを探索対象に含める場合は、実行前の確認後に限り有効になります。試験先は開発環境にしてください。

JUnit XMLとローカルHTMLレポートを実行ごとのフォルダへ保存します。VCR証跡は任意で、応答本文を含むことがあるため既定では作成しません。Schemathesisは通常のPython依存には含めませんが、配布版にはGUIの探索試験を使えるよう同梱します。GitHubや外部レポートサービスへの送信は行いません。

### 配布用アプリを作る（開発者向け）

Python本体と実行依存（Schemathesisを含む）を同梱したポータブル版と、Windowsインストーラーを作成する。ビルドPCには必要なPython依存、Node.js依存、Rust/Cargo依存をあらかじめインストールしておく。配布ビルド時にネットワークから依存を取得しない。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package-portable.ps1
```

ポータブル版は `dist/openapi-test-tool-portable/` に生成される。exe単体ではなくフォルダ全体を配布する。MSIとNSISインストーラーは `dist/openapi-test-tool-installers/` に生成される。配布先にPython、Node.js、Rustの開発環境は不要。Tauriアプリの画面表示にはWindowsのWebView2が必要で、Windows 10 version 1803以降とWindows 11には通常含まれている。WebView2が未導入の環境では、既定のインストーラーがランタイム取得にネット接続を使う場合がある。

Windowsで一般利用者へ配布する場合は、信頼されたコード署名証明書で署名したビルドを使う。未署名のビルドはDevice Guardなどのアプリ制御ポリシーで実行を拒否されることがある。GitHub Actionsで署名ビルドを有効にするには、公開されたコード署名証明書のPFXを用意し、リポジトリのActions変数 `WINDOWS_SIGNING_ENABLED` を `true` に設定する。さらにActions secretsに `WINDOWS_SIGNING_CERTIFICATE_PFX_BASE64`（PFXファイルのBase64）と `WINDOWS_SIGNING_CERTIFICATE_PASSWORD` を登録する。PFXとパスワードはリポジトリへコミットしない。署名情報が未設定ならWindowsパッケージworkflowは署名なし成果物を作らず、ビルドをスキップする。

`npm run tauri build` は開発ビルド用であり、同梱Pythonを準備しない。配布物の作成には上記スクリプトを使う。

### ローカル検証

GitHubを使わず、次のコマンドでPython・GUI・RustのテストとLintをまとめて確認できる。

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify-local.ps1
```

---

## 使用前に用意するファイル

`openapi.json`（対象APIの定義）以外は全部オプションで、使う機能に応じて必要なものだけ
用意すればよい。サンプルと詳しい説明は [`examples/`](examples/README.md) を参照。
対象APIの実装言語は問わない（HTTPとSQLしか使わないため）。PHP（特にフレームワーク無し）
で`openapi.json`をまだ持っていない場合は、GUIでCopilot用の依頼文をコピーして下書きを作成・確認できる。手順は [docs/php_openapi_setup.md](docs/php_openapi_setup.md) を参照。

| ファイル | 必須/任意 | 必要になる場面 |
|---|---|---|
| `openapi.json` | 必須 | 常に |
| `auth_config.yaml` | 任意 | ログイン方式の認証を使う場合 |
| `config.json` | 任意 | `--setup`/`--teardown`、DB検証を使う場合 |
| `setup.sql` / `teardown.sql` | 任意 | 試験前後にDBを初期化する場合 |
| `mapping.yaml` | 任意 | DBシナリオの叩き台を自動生成する場合 |
| `scenarios.yaml` | 任意 | DB検証（Layer 2）を行う場合 |

---

## openapi-test-gen

### 前提

- Python 3.10+

### セットアップ

```sh
pip install -r requirements.txt
```

### 使い方

```sh
python src/cli.py <openapi.json> [オプション]
```

### 引数・オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `<input>` | openapi.json のパス（必須）| — |
| `-o, --output <path>` | JSON 出力先 | `./test_cases.json` |
| `--excel-output <path>` | Excel (.xlsx) も出力する場合に指定 | — |
| `--operations <ops>` | 対象 operationId をカンマ区切りで指定 | 全件 |
| `--exclude-ops <ops>` | 除外する operationId をカンマ区切りで指定 | — |
| `--no-normal` | 正常系ケースを生成しない | — |
| `--no-abnormal` | 異常系ケースを生成しない | — |
| `--dry-run` | ケース数のみ表示し、ファイルを出力しない | — |
| `--fail-if-exists` | 出力先が存在する場合はエラー終了 | — |
| `--log-level <level>` | ログレベル（debug/info/warn/error）| `info` |

### 使用例

```sh
# JSON + Excel を両方出力
python src/cli.py openapi.json \
  --output test_cases.json \
  --excel-output 試験仕様.xlsx

# 特定 operation のみ対象
python src/cli.py openapi.json \
  --excel-output 試験仕様.xlsx \
  --operations createUser,getUser

# ケース数の確認のみ（ファイル出力なし）
python src/cli.py openapi.json --dry-run
```

### 生成されるテストケースの種類

**正常系**

| keyword | 内容 |
|---|---|
| `optional` | 省略可能パラメータを省略して正常に動作すること |
| `enum` | 有効な enum 値を送信して正常に動作すること |
| `minLength` | 最小長ちょうどの文字列で正常に動作すること |
| `maxLength` | 最大長ちょうどの文字列で正常に動作すること |
| `minimum` | 最小値ちょうどで正常に動作すること |
| `maximum` | 最大値ちょうどで正常に動作すること |
| `pattern` / `format` | 正規表現・フォーマットに一致する値で正常に動作すること |

**異常系**

| keyword | 内容 |
|---|---|
| `required` | 必須フィールド欠落（フィールドを省略） |
| `required` | キーあり・空値（空文字を送信） |
| `type` | 型不正値（文字列フィールドに数値など） |
| `enum` | enum 外の値 |
| `minLength` | 最小長-1 文字 |
| `maxLength` | 最大長+1 文字 |
| `minimum` / `maximum` | 境界値の外側 |
| `pattern` / `format` | 不正な形式の値 |
| `additionalProperties` | スキーマ外キーを追加（`additionalProperties: false` の場合） |

必須パラメータと必須リクエストボディをまとめた、operation単位の最小有効リクエストも生成します。必須のpath/query/header/cookie parameterとJSON・multipart bodyを送信し、optional parameterは省略します。安全な値を合成できないoperationではこの共通ケースを省略して警告します。`in: cookie` のケースは Cookie ヘッダとして送信します。

正常系は特定の `200` に固定せず、OpenAPIに定義された成功レスポンス（個別statusまたは `2XX`）のどれかを受け付けます。実際に返ったstatusに対応するレスポンス本文のJSON schema、Content-Type、requiredレスポンスヘッダの存在と、返却されたヘッダ値のschemaを runner で検証します。複数の成功statusを同じリクエストで個別に発生させる条件まではOpenAPIから決められないため、その分岐を試すシナリオは別途記述してください。詳細は[自動試験の範囲](docs/automation-boundary.md)を参照してください。

### Excel 出力フォーマット

`test_spec` シートに以下の列を出力します。

| 列 | ヘッダ | 内容 |
|---|---|---|
| A | 試験ID | 自動採番（例: TC-GET-01-001）|
| B | operationId | OpenAPI の operationId |
| C | 概要 | テストケースの概要 |
| D | パス | API パス |
| E | メソッド | HTTP メソッド |
| F | in | パラメータ区分（path / query / body）|
| G | パラメータ名 | フィールド名 |
| H | Keyword | バリデーションキーワード |
| I | 観点 | 正常系 / 異常系 のカテゴリ |
| J | 入力/操作 | 送信する値 |
| K | 期待ステータス | 期待 HTTP ステータスコード |
| L | 期待レスポンスボディ | OpenAPI定義のJSON schemaに従うこと 等 |
| M | 期待レスポンスヘッダ | Content-Type 等 |
| N | 期待応答時間 | 3秒以内 等 |
| O | 期待結果 | 人間可読な期待結果 |
| P | 判定 | OK / NG / 未実施（ドロップダウン）|
| Q | 備考 | 補足事項 |

---

## openapi-test-run

生成した Excel を入力として、実際の API サーバーに対して HTTP リクエストを送信し、結果を Excel に書き戻すランナーです。

詳細は [runner/README.md](runner/README.md) を参照してください。

### 基本的な使い方

```sh
pip install -r requirements.txt

cd runner
python runner.py 試験仕様.xlsx openapi.json \
  --base-url http://192.168.1.100:8080
```

実行後、`試験仕様_result.xlsx` に結果が書き込まれます。

### 結果列（ランナー実行後に追記される列）

| ヘッダ | 内容 |
|---|---|
| 実行日時 | ISO 8601 形式 |
| 実測ステータス | 実際の HTTP ステータスコード |
| 実測ヘッダ | レスポンスヘッダ |
| 実測ボディ | レスポンスボディ（デフォルト 21 文字で切り捨て）|
| 応答時間(ms) | レスポンスタイム |
| 判定詳細 | NG・Warning の理由 |
| 実行コマンド | 実際に実行した curl コマンド（デバッグ用）|

---

## テスト

API 契約、業務シナリオ、DB 照合の自動化範囲と必要な人手確認は、[自動試験の範囲](docs/automation-boundary.md)を参照してください。

**ジェネレーター**

```sh
python -m pytest tests/ -q
```

**ランナー**

```sh
python -m pytest runner/tests/ -q
```

**契約層の探索的ファジング（schemathesis）**

`runner.py`（Layer1）は境界値・enum等を決定論的に列挙した回帰スイートだが、これとは別に
CIの `e2e` ジョブで [schemathesis](https://schemathesis.readthedocs.io/) による
hypothesisベースの探索的ファジングを `docs/openapi.json` に対して並走させている
（[docs/run_schemathesis.py](docs/run_schemathesis.py)）。役割が異なる（決定論的な既知の
回帰チェック vs. 人間が想定していない組み合わせの継続的な探索）ため、こちらの結果はCIを
ブロックせず、JUnit XML・カセット（実施したリクエスト/レスポンスの記録）を証跡として
アーティファクトに残すのみ。

## Lint

実バグに直結する項目（未使用/未定義変数、`raise ... from` 漏れ等）に絞った軽量なLintをCIで実行している。
import順序等のスタイル系ルールは対象外。

```sh
pip install -r requirements-dev.txt
ruff check .                    # Python（src/ runner/ gui/ docs/ tests/）

cd gui-tauri
npm run lint                    # JavaScript（src/main.js）
cargo clippy --all-targets -- -D warnings --manifest-path src-tauri/Cargo.toml   # Rust
```

POSTで配列を複数行へ保存するAPIは、[配列からの保存照合](docs/post-array-testing.md)を参照してください。UIで親項目・固定値・日時・JSON・DB参照を設定できます。

- GETの複雑な取得条件・入れ子JSONのDB照合: [期待値SQLの設定](docs/sql-response-testing.md)
