# 自動試験ランナー 実装計画書

## 概要

OpenAPI テスト仕様ジェネレータが出力した試験項目 JSON / Excel を入力として、
実際の API サーバーに対して HTTP リクエストを送信し、結果を Excel に書き出すランナー。

---

## アーキテクチャ

```
入力
├─ 試験項目 Excel (.xlsx)       ← excel_reader.py が読み込む
└─ openapi.json                ← request_builder.py が baseline 生成に使用

ランナー本体 (runner.py)
├─ excel_reader.py      試験項目 Excel → RunCase[] に変換
├─ request_builder.py   RunCase + openapi.json → curl 引数を組み立て
├─ http_client.py       subprocess + curl で実行 → RunResult
├─ verifier.py          RunResult を Level 1〜3 で検証 → verdict
└─ excel_writer.py      verdict + 実測値を結果 Excel に書き出し

出力
└─ {元ファイル名}_result.xlsx   ← 元の試験項目列に P〜U 列を追記
```

---

## データ構造

### RunCase

試験項目 Excel の 1 行を表す実行単位。

```python
@dataclass
class RunCase:
    id: str                    # TC-xxx-001
    operation_id: str
    path: str                  # /users/{id}
    method: str                # GET / POST / PUT / DELETE
    param_in: str              # path / query / body
    param_name: str
    input_value: str           # "1" / "（省略）" / "（フィールドを省略）"
    expected_status: str       # "200" / "400" etc.
    expected_response_body: str
    expected_response_header: str
    expected_response_time: str  # "3秒以内"
    expected_result: str
```

### RunResult

HTTP 実行後の実測値。

```python
@dataclass
class RunResult:
    case: RunCase
    actual_status: int
    actual_body: str           # レスポンスボディ（文字列）
    actual_headers: dict[str, str]
    elapsed_ms: float
    curl_exit_code: int        # curl のプロセス終了コード
    error: str | None          # タイムアウト / 接続失敗などのエラーメッセージ
```

### ResponseSchema

verifier.py が検証に使う期待値の構造体。RunCase から派生。

```python
@dataclass
class ResponseSchema:
    expected_status: int
    expected_content_type: str | None   # "application/json" / None
    expected_response_time_ms: float    # 3000.0
```

---

## コンポーネント仕様

### http_client.py ✅ 確定（変更あり）

`requests.Session` は使用しない。`subprocess` で `curl.exe` を呼び出して実行する。

#### 実行環境

- ランナーは **Windows 上（PowerShell / CMD）** で動作する
- `curl.exe` は Windows 標準の curl を使用する（WSL の curl は使わない）
- VM の API サーバーに対してホストマシンから HTTP リクエストを投げる構成

#### ヘルスチェック

ランナー起動時に以下を実行する。

- `GET {base_url}{health_path}` を curl.exe で叩く
- `health_path` のデフォルト: `/health`（`--health-path` オプションで変更可能）
- 接続失敗時はエラーメッセージを表示して **終了コード 3** で即時終了する

#### curl の組み立てルール

| 項目 | 設定 |
|---|---|
| コマンド | `curl.exe` |
| ベース URL | `--base-url` オプションで指定（例: `http://192.168.1.100:8080`）|
| 認証 | 環境変数 `TEST_AUTH_TOKEN` → `Authorization: Bearer {TOKEN}` ヘッダ |
| タイムアウト | `--max-time 10` |
| 応答時間 | `--write-out "\n%{http_code}\n%{time_total}"` で取得し ms に変換 |
| レスポンスボディ | `-o -` で stdout に出力 |
| JSON ボディ | `-H "Content-Type: application/json; charset=utf-8"` + `-d "{json}"` |
| 文字コード | UTF-8（日本語フィールド値あり）。JSON は `json.dumps(body, ensure_ascii=False)` で生成 |

#### stdout のパース方式

```python
result = subprocess.run(
    ["curl.exe", "-s", "-X", method,
     "-w", "\n%{http_code}\n%{time_total}",
     "--max-time", "10",
     "-H", f"Authorization: Bearer {token}",
     "-H", "Content-Type: application/json; charset=utf-8",
     url,
     *body_args],
    capture_output=True, text=True, encoding="utf-8"
)
lines = result.stdout.rsplit("\n", 2)
body       = lines[0]
http_code  = int(lines[1])
elapsed_ms = float(lines[2]) * 1000
```

stdout の末尾2行が `{http_code}\n{time_total}` の形式で付与される。

#### body_args の組み立て

| param_in | 変換先 |
|---|---|
| `path` | URL に代入（`/users/{id}` → `/users/1`）|
| `query` | URL クエリ文字列（`?page=1`）|
| `body` | `-d` + `json.dumps(body_dict, ensure_ascii=False)` |

`input_value = "（省略）"` または `"（フィールドを省略）"` の場合はそのフィールドを省略。

---

### request_builder.py ✅ 確定（追記あり）

#### baseline 自動生成（body テスト用）

body 系テストではテスト対象フィールド以外の required フィールドを
openapi.json のスキーマから自動生成した有効値で補完する。

`_expand_required` 関数がスキーマを再帰的に走査し、
以下のルールで baseline 値を生成する。

| 型・制約 | 生成値 |
|---|---|
| `type: string` | `"test"` |
| `type: string, format: email` | `"test@example.com"` |
| `type: string, format: date` | `"2024-01-01"` |
| `type: string, format: date-time` | `"2024-01-01T00:00:00Z"` |
| `type: string, enum: [...]` | `enum[0]` |
| `type: string, minLength: N` | `"a" × N` |
| `type: integer, minimum: N` | `N` |
| `type: integer` | `1` |
| `type: boolean` | `true` |

既存の `FORMAT_SAMPLES` テーブル（`src/samples/format-samples.ts` の正常サンプル値）を
Python 側に移植して流用する。

---

### verifier.py ✅ 変更なし

RunResult と ResponseSchema を照合し、3 段階で判定する。

#### Level 1: ステータスコード（必須）

- `actual_status == expected_status` → Pass
- 不一致 → Fail（NG）

#### Level 2: 応答時間

- `elapsed_ms <= expected_response_time_ms` → Pass
- 超過 → Warning（NG 扱い）
- curl タイムアウト（curl exit code 28）→ Fail

#### Level 3: Content-Type ヘッダ（あれば）

- `expected_content_type` が空文字でない場合のみ検証
- `actual_headers["Content-Type"]` が `expected_content_type` を前方一致 → Pass
- 不一致 → Fail

**verdict の最終判定**: Level 1 が最優先。Level 1 Pass の場合のみ Level 2/3 を評価。

---

### excel_reader.py ✅ 変更なし

試験項目 Excel（`test_spec` シート）を読み込み RunCase[] に変換する。

- ヘッダ行（行 4）でカラム名 → 列インデックスのマッピングを構築
- 行 5 以降をデータ行として読み込む
- `期待ステータス` / `期待レスポンスボディ` / `期待レスポンスヘッダ` / `期待応答時間` を RunCase に格納

---

### excel_writer.py ✅ 変更なし（列ヘッダ名確定）

既存の試験項目 Excel に P〜U 列を追記して結果ファイルとして保存する。

| 列 | ヘッダ名 | 内容 |
|---|---|---|
| P | 実行日時 | ISO 8601 形式 |
| Q | 実測ステータス | curl で取得した実際のステータスコード |
| R | 実測ヘッダ | Content-Type + OAS 定義済みヘッダ（JSON 文字列） |
| S | 実測ボディ | レスポンスボディ（21 文字超は短縮） |
| T | 応答時間(ms) | curl の `%{time_total}` を ms に変換した値 |
| U | 判定詳細 | NG・スキップの理由 |
| V | 実行コマンド | 実際に実行した curl コマンド文字列 |

- デフォルト保存先: `{元ファイル名}_result.xlsx`（元ファイルには上書きしない）
- `--output` オプションで任意パスを指定可能

---

## 実行方式 ✅ 確定

- **順次実行**（並列実行なし）
- テストデータ（DB 投入等）はランナーのスコープ外
- `--base-url` で指定した VM 上にリソースが事前に存在する前提で実行する
- path パラメータのテスト（例: `GET /users/{id}`）は対象リソースが存在していることを前提とする

---

## CLI インターフェース

```
python runner.py <excel_path> <openapi_path>
  --base-url     <url>   API サーバーのベース URL（必須）
  --output       <path>  結果 Excel の出力先（省略時: {元ファイル名}_result.xlsx）
  --health-path  <path>  ヘルスチェック用パス（省略時: /health）
  --fail-fast            Level 1 NG が出た時点で実行を停止
```

環境変数:
- `TEST_AUTH_TOKEN`: Bearer トークン（未設定時は Authorization ヘッダを付与しない）

---

## 終了コード ✅ 変更なし

優先度: `3 > 1 > 2 > 0`

| コード | 意味 |
|---|---|
| 0 | 全ケース OK |
| 1 | 1 件以上 NG（ステータス不一致 / Content-Type 不一致）|
| 2 | 1 件以上 Warning（応答時間超過）|
| 3 | 実行エラー（curl 接続失敗 / Excel 読み込み失敗 / 設定不正）|

---

## テスト戦略 ✅ 確定（変更あり）

### http_client.py のユニットテスト

`pytest-httpserver` は使用しない。
`subprocess.run` を `unittest.mock.patch` でモックし、
stdout の形式が正しくパースされることを確認する。

```python
# テスト例
with patch("subprocess.run") as mock_run:
    mock_run.return_value = MagicMock(
        stdout="{'id':1}\n200\n0.123",
        returncode=0
    )
    result = execute(case, base_url="http://dummy")
    assert result.actual_status == 200
    assert result.elapsed_ms == pytest.approx(123.0)
```

### 結合テスト（test_runner_integration.py）

`pytest-httpserver` で実際に localhost サーバーを立て、
`--base-url http://localhost:{port}` を渡して
`curl.exe` がそこに到達できることを確認する。

ホスト（Windows）→ VM の構成と同じ経路を localhost で再現する形。

### その他ユニットテスト

- `request_builder.py`: RunCase → curl 引数・URL の変換テスト、baseline 生成テスト
- `verifier.py`: Level 1〜3 の各判定ロジックのテスト
- `excel_reader.py`: fixtures の xlsx を読み込み RunCase への変換テスト
- `excel_writer.py`: RunResult を受け取り P〜U 列が正しく書き込まれるテスト

---

## 実装順序（Step 1〜13）

| Step | 内容 |
|---|---|
| 1 | プロジェクト構成・依存関係（openpyxl, pytest, pytest-httpserver）|
| 2 | データ構造定義（RunCase / RunResult / ResponseSchema）|
| 3 | excel_reader.py 実装 + テスト |
| 4 | request_builder.py 基本実装（path / query 変換）+ テスト |
| 5 | request_builder.py baseline 生成（body テスト用）+ テスト |
| 6 | http_client.py 実装（subprocess + curl）+ モックテスト |
| 7 | http_client.py 結合テスト（pytest-httpserver）|
| 8 | response_schema.py 実装（RunCase → ResponseSchema 変換）|
| 9 | verifier.py 実装（Level 1〜3）+ テスト |
| 10 | excel_writer.py 実装（P〜U 列書き込み）+ テスト |
| 11 | runner.py 実装（全コンポーネント統合・CLI）|
| 12 | E2E テスト（pytest-httpserver でフル実行）|
| 13 | ドキュメント整備・README 更新 |

---

## 将来対応（今回スコープ外）

**`--operations` で対象 operationId を絞り込むオプション**

例: `--operations getUser,createUser` で指定した operationId のみ実行する。
今回は全件実行のみ対応する。

---

**path パラメータが複数あるエンドポイントの baseline 自動生成**

例: `/users/{id}/posts/{post_id}` で `post_id` をテストする場合、
テスト対象外の `id` に対しても baseline 値（`minimum` 値等）を自動生成する必要がある。

今回対象の openapi.json はすべて単一 path パラメータのため実装対象外とする。
将来的には `request_builder.py` の `_expand_required` と同様のロジックで対応する。

---

## 未確定事項（要確認）

### ℹ️ 将来検討

**Q1. `--fail-fast` 以外の実行制御オプションは必要か？**

例: `--operations getUser,createUser` で対象 operationId を絞り込む。
