# ログインAPIの検証用設定

実サーバーではなく、提示仕様を基に作ったローカル検証用APIです。資格情報は公開可能な架空値のみです。

- POST `/v1/auth/login`: 必須stringのusername/password。
- 必須レスポンス: stringのid、date-timeのcreated_datetime。
- `auth.json`: token_path=`id`、header_name=`auth-key`、header_format=`{token}`。
- `/v1/protected`: 取得したidによる認証を確認するための検証用API。
- **成功200、入力不正400、認証失敗401は未確定仕様の仮置きです。実APIの期待結果として確定した値ではありません。**

UIではAPI定義を読み込み、「詳細設定（認証・DB・実行方法）」でログイン認証を有効化し、login操作・ログインボディ・上記3項目を入力します。

## 確認結果

2026-10-12、実HTTP通信による検証:

| 検証 | 結果 |
| --- | --- |
| 生成した契約/認証29ケース＋明示的な認証失敗5ケース（2026-10-13更新） | 34実行成功 |
| id欠落・id型違い・日時欠落・日時形式不正 | 全てNGを検出 |
| 不正パスワード受理・不正型受理・認証チェック無視 | 全てNGを検出 |
| ChromiumのUIからログインし、後続APIの正常/認証なし/不正IDを実行 | 3ケース成功 |
| 実CLIでログインして生成された契約ケースを実行、Excel/JUnit出力 | 成功 |
| 結果Excel/実行コマンドからパスワードと認証用idを伏せる | 修正後に確認済み |

**空文字は必須stringだけでは禁止されません。** 現在は正常値を指定した項目の空文字を成功扱いで自動生成せず、`failure-scenarios.json`でusername空文字・password空文字・両方空文字の期待statusを明示しています。このファイルはUIのDB確認設定としても読み込めます（DB照合なしのレスポンス確認ケース）。401は検証用APIの仮定なので、実APIの仕様に合わせて変更してください。誤ったパスワード・存在しないユーザーなどの認証成否はOpenAPIの型だけでは導けません。

同じく、期限切れ・ログアウト・権限差・ロックアウトは今回仕様にないため未検証です。

再実行:

```sh
python -m pytest runner/tests/test_login_e2e.py -q -s
```

UI検証はビルド済みUI・Playwright・Chromiumのある環境で `OTG_BROWSER_TEST=1 python -m pytest gui/tests/test_browser_login.py -q`。

既存のログイン設定を使った実行では、指定ログイン操作のtoken_pathだけを証跡で伏せます。別APIの通常のidは伏せません。元のAPI定義は書き換えず、レスポンスの必須・型の検証も維持します。
