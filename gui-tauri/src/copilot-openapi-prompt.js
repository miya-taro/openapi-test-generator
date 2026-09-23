export const COPILOT_OPENAPI_PROMPT = `あなたは素のPHPで実装されたAPIの仕様調査担当です。VS Codeで開いているPHPプロジェクトを調べ、実装からOpenAPI 3.0.3の下書きを作成してください。

調査対象: エントリポイント、ルーティング、include/require先、$_SERVER['REQUEST_METHOD']、$_GET、$_POST、$_COOKIE、$_FILES、php://input、ヘッダー、入力検証、認証・認可、http_response_code、json_encode、DBクエリ。必要なら関連ファイルをたどってください。

出力するファイル:
1. openapi.draft.json — JSON形式のOpenAPI 3.0.3。実在すると根拠を確認できたAPIだけをpathsに記載し、各操作に一意のoperationId、method、path、確認できた入力とレスポンスを記載する。推測だけで型、必須、ステータス、URL、認証方式を確定しない。
2. openapi.review.md — 各操作について根拠となるPHPファイルと行、URLとHTTPメソッドの決め方、入力・検証・レスポンスの根拠、未確認事項を表にする。動的ルーティング、共通関数、include先、DB依存で断定できない点は「要確認」と明記する。見つけたが仕様化できないAPI候補も列挙する。
3. openapi.db-evidence.json — DBを変更するPOST/PUT/PATCH/DELETE操作について、PHPコードから直接確認できるSQLのテーブル・カラム候補を次の形式で記録する。SQLの実行経路や動的SQLなどで断定できない候補は複数残し、根拠のない値を作らない。

{
  "format": "api-tester.php-db-evidence",
  "schemaVersion": 1,
  "operations": {
    "実在するoperationId": {
      "tables": [
        {
          "table": "SQLに記載された実テーブル名",
          "action": "insert",
          "columns": ["SQLで直接確認できる実カラム名"],
          "evidence": [{"file": "PHPプロジェクトからの相対パス", "line": 123}]
        }
      ]
    }
  }
}

operationsのキーはopenapi.draft.jsonに実在するoperationIdだけにし、tablesはSQLを直接追えた書き込み系操作だけを含めてください。actionはselect、insert、update、delete、upsert、unknownのいずれかを指定します。1操作が複数テーブルを変更する場合は、テーブルごとに候補を分けてください。fileには..を含めず、lineには実際の行番号を指定してください。SQLにない値やDBのレコード内容、秘密情報、SQL全文は出力しないでください。DBスキーマファイルが開かれている場合は照合に使い、ない場合は実DB照合が未実施とreview.mdに明記してください。

既存のPHPコードを変更したりAPIを呼び出したりしないでください。記載できない情報は作らず、レビュー用ファイルに質問として残してください。生成後はJSON構文を確認し、OpenAPI pathsの全操作に一意のoperationIdがあり、DB根拠JSONのoperationIdがOpenAPIと一致することを確認してください。PHP SQL根拠JSONはapi-testerへ取り込んだ後も候補扱いで、人が確認するまで確定情報にしないでください。`;
