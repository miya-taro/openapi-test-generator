# API Tester デスクトップアプリ

TauriとVanilla JavaScriptで作られた正式GUIです。Pythonの `src/`、`runner/`、`workflow/` をローカル子プロセスとして実行します。

素のPHP APIにOpenAPI定義がない場合は、「対象を登録」の案内からCopilot用の依頼文をコピーできます。VS CodeでPHPプロジェクトを開いて下書きと根拠資料を作り、人が確認した下書きをGUIへ読み込んで試験を始めます。ソースをGitHubリポジトリへ登録する必要はありません。

「テスト生成・実行」と「DBシナリオ」の各画面で、まずケースマスターと汎用試験仕様Excelを作り、HTTP送信やDB接続をせずに内容を確認できます。ケースごとに `下書き → レビュー済み → 承認済み` と進めると、承認済み実行ボタンが使えるようになります。未承認のまま動作を試したい場合は「未承認で予備実行」を選びます。ソース仕様やシナリオ定義が変わると承認状態を引き継がず、再レビューを求めます。

OpenAPIベースの探索試験は任意機能です。ソースから実行する場合は、利用するPython環境へ `python -m pip install -r docs/requirements-schemathesis.txt` でSchemathesisを追加すると、「テスト生成・実行」の折りたたみ欄に表示されます。配布ビルドにはSchemathesisも同梱されます。既定の探索対象は選択中のGETのみ、最大10例/操作、1 worker、毎秒5リクエスト以下です。認証設定を使う場合はtoken取得のためログインAPIへPOSTします。OpenAPIに認証定義があれば、認証あり・なし・不正認証を試して拒否を検証します。仕様外メソッドのプローブは既定で無効で、更新系APIを含める場合はGUIで明示確認します。VCR証跡は任意で、応答本文が含まれる可能性を画面と結果レポートに表示します。すべての成果物はローカルの実行フォルダに保存します。

両方の層でLayer 1/Layer 2のIDを試験仕様Excel、結果Excel、JUnit XML、HTMLレポートで共通して使います。社内指定Excelテンプレートは未提供のため、現在は汎用の試験仕様書を出力します。テンプレートが確定したら列マッピングを追加してください。

## 開発実行

```powershell
npm ci
npm run tauri dev
```

Python 3.10以上、Node.js、Rustが必要です。起動できない場合は、まずリポジトリ直下で `python --version` と `python workflow/cli.py --help` を確認してください。

## ローカル検証

```powershell
powershell -ExecutionPolicy Bypass -File ..\scripts\verify-local.ps1
```

## 配布ビルド

```powershell
powershell -ExecutionPolicy Bypass -File ..\scripts\package-portable.ps1
```

リポジトリ直下の `dist/openapi-test-tool-portable/` にPython本体・依存パッケージとソースを含むポータブル版、`dist/openapi-test-tool-installers/` にMSI/NSISインストーラーが生成されます。ポータブル版はexeだけでなくフォルダ全体を配布してください。配布先にPythonは不要です。画面表示にはWebView2が必要です。Windows 10 version 1803以降とWindows 11には通常含まれています。WebView2がない場合、既定のインストーラーがランタイム取得にネット接続を使う場合があります。依存パッケージの取得なしでビルドするため、ビルドPCにはPython/Node/Rustの依存関係とCargoキャッシュが必要です。

通常の `npm run tauri build` は同梱Pythonを作成しないため、配布物には上記スクリプトを使用してください。
