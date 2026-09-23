# 素のPHPからOpenAPIを作る精度評価サンプル

このフォルダーは、VS CodeのGitHub Copilotが素のPHPコードからどれだけ正確なOpenAPI草案を作れるかを、人が再現可能な方法で評価するための合成サンプルです。実在のサービス、認証情報、顧客データは含みません。PHPコードは解析用の素材であり、APIサーバーとして起動する必要はありません。

## 評価手順

1. VS Codeでこのフォルダーを開き、Copilot Chatを選ぶ。
2. api-testerの「対象を登録」からCopilot用プロンプトをコピーして貼り付ける。
3. `php/` 以下のコードを調べて、`openapi.draft.json` と `openapi.review.md` を作るよう指示する。生成物は `actual/` フォルダーに保存するよう追加指示してよい。
4. 生成されたOpenAPIと根拠資料を [`scorecard.md`](scorecard.md) に沿って [`expected/openapi.json`](expected/openapi.json) と [`expected/openapi.review.md`](expected/openapi.review.md) に照合する。
5. 点数だけでなく、重大な誤り（存在しないAPIの追加、実在APIの欠落、メソッド・パスの誤り、根拠のない必須指定）があれば記録する。

この評価はCopilotの実行結果を自動採点するものではありません。API契約の細かな意味は人が確認します。期待ファイルとのテキスト差分ではなく、エンドポイント、入力、応答、ステータスコードの意味を比較してください。

## サンプルの構成

- `php/public/index.php`: HTTPメソッドとURLパスからハンドラを選ぶ。
- `php/src/users.php`: 一覧、詳細取得、作成の処理と入力検証。
- `php/src/http.php`: JSON応答と共通エラー形式。
- `php/src/db.php`: 環境変数からPDO接続を作る。
- `php/schema.sql`: PostgreSQL用の最小テーブル定義。
- `expected/openapi.json`: このサンプルを読んだ場合の人手作成の基準OpenAPI。

コード中のDBドライバーやDB接続環境変数は、API契約の評価対象ではありません。実案件の精度を判断するには、実際のPHPバージョン、URLとファイルの対応、ルーター、入力取得方法が代表される匿名化コードでも同じ評価を行ってください。
