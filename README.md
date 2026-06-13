# openapi-test-gen / openapi-test-run

OpenAPI 3.x 定義ファイルから **インターフェース観点のテスト仕様を自動生成**し、実際の API サーバーに対して **自動試験を実行**するツールセット。

```
openapi.json
    │
    ▼  openapi-test-gen (TypeScript)
試験仕様 Excel（test_spec シート）
    │
    ▼  openapi-test-run (Python / runner/)
結果 Excel（実測値・判定・実行コマンドを追記）
```

---

## 構成

```
api test generator/
├── src/                  # openapi-test-gen（試験仕様ジェネレーター）
│   ├── cli.ts            # CLI エントリーポイント
│   ├── parser/           # OpenAPI パース
│   ├── extractor/        # パラメータ・ボディフィールド抽出
│   ├── generator/        # テストケース生成ルール
│   │   └── rules/        # common / string / integer / array / object
│   ├── id-assigner/      # 試験 ID 採番
│   └── renderer/         # JSON / Excel 出力
├── runner/               # openapi-test-run（試験実行ランナー）
│   └── README.md         # ランナー詳細ドキュメント
└── docs/                 # サンプル OpenAPI・出力ファイル
```

---

## openapi-test-gen

### 前提

- Node.js 18+
- pnpm

### セットアップ

```sh
pnpm install
```

### 使い方

```sh
pnpm exec tsx src/cli.ts <openapi.json> [オプション]
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
| `--enum-full-coverage` | enum の全値を正常ケースとして生成 | false |
| `--dry-run` | ケース数のみ表示し、ファイルを出力しない | — |
| `--fail-if-exists` | 出力先が存在する場合はエラー終了 | — |
| `--log-level <level>` | ログレベル（debug/info/warn/error）| `info` |

### 使用例

```sh
# JSON + Excel を両方出力
pnpm exec tsx src/cli.ts openapi.json \
  --output test_cases.json \
  --excel-output 試験仕様.xlsx

# 特定 operation のみ対象
pnpm exec tsx src/cli.ts openapi.json \
  --excel-output 試験仕様.xlsx \
  --operations createUser,getUser

# ケース数の確認のみ（ファイル出力なし）
pnpm exec tsx src/cli.ts openapi.json --dry-run
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
cd runner
pip install -r requirements.txt

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

**ジェネレーター（TypeScript）**

```sh
pnpm test
```

**ランナー（Python）**

```sh
cd runner
python -m pytest tests/ -q
```
