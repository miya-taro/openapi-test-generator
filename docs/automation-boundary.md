# 自動試験の範囲

このツールは、OpenAPI からテストを作り、指定した API / DB に対して実行できます。自動化の可否は「実行できるか」と「何を正解と判定するか」を分けて考えます。

## OpenAPI から自動生成できる契約試験

OpenAPI に記述された operation、path/query/header/cookie parameter、JSON・multipart request body の型、必須性、境界値、enum、pattern をもとにリクエストケースを生成します。required input を安全に合成できる operation には、必須パラメータと必須requestBodyをまとめた「最小有効リクエスト」も1件生成します。制約に合う代表値を合成できない場合は、この共通ケースを省略して警告します。

正常系ケースは `2xx` として、OpenAPI に定義された成功status（個別コードまたは `2XX` 範囲）のいずれかを受け付けます。実測statusに応じて、そのstatusのJSONレスポンスschema、Content-Type、required response headerの存在と、返却されたresponse header値のschemaを検証します。複数の成功statusがあっても、同じ入力が全statusを発生させるとは限らないため、statusごとに同じ入力を複製して強制することはしません。どの条件で各応答になるか仕様から分からない場合、個々の分岐を発生させるシナリオは別途必要です。

response headerのschemaは、標準のsimple形式で受け取った値を型に変換して検証します。Content-Typeは実測statusに定義されたmedia typeのいずれかと照合します。レスポンス本文のschema検証対象は `application/json` と `+json` media typeです。

`format`（email/date/date-time など）は正常値の例を生成できます。不正値ケースも生成しますが、OpenAPI の format はサーバーが必ず拒否するという保証ではありません。現在の生成ケースは 4xx を期待するため、API が format を検証する契約かを確認してから承認してください。レスポンスschema検証ではFormatCheckerを有効にし、対応するdate-time・date・email等の形式を検証します。未知の独自formatは検証できません。

スキーマ違反のケースは、OpenAPI が違反ごとのエラーコードを割り当てていないため、特定の `400` ではなく `4xx` を期待します。合格にするのはOpenAPIに定義した4xxです。定義外の4xxを一律に合格にはしません。認証で401と403の両方が定義されている場合、認証異常ケースはその2コードを許容し、それぞれのレスポンス契約も検証します。個々の入力エラーに対する正確な status やエラー内容は、OpenAPI に対応関係がある場合か、人がシナリオに指定した場合に検証します。

request body があり、operation に `415` 応答が定義されている場合は、本文を付けたまま未対応 Content-Type を送るケースを生成します。標準の `Content-Type` parameter としての型試験は行わず、この専用ケースで未対応 media type の応答を確認します。認証試験は OpenAPI の security scheme が定義された operation が対象です。

この生成器は OpenAPI に書かれていないルート、DB に存在する値、重複キー、更新後の業務状態を推測しません。生成できない制約の組み合わせは、誤った正常ケースを作らず、その境界ケースを省略して警告します。

## DB・業務シナリオ

`scenarios.yaml` にリクエスト、前提データ、API 応答の期待値、API 実行後の DB 期待状態を記述すれば、Layer 2 が API 呼び出しと DB 照合を実行します。PostgreSQL / InfluxDB の検証や setup / teardown も利用できます。

初版ではUIでAPI項目とDBテーブル・カラム・抽出条件を人が設定します。関係性や「この入力ならこの業務状態が正しい」という期待値をコードから推測しません。重複メール、存在しない ID、状態遷移なども、テストデータと期待結果をシナリオに書けば自動実行できます。

## 運用上必要な準備

実際の API に送るには Base URL、必要な認証、テスト用データ、DB の接続先が必要です。POST / PUT / PATCH / DELETE を含む試験は状態を変更するため、専用のテスト環境と再現可能な setup / teardown を用意してください。試験ケースの生成・実行・結果出力は自動化できますが、変更された環境が試験用かどうかはツールが判断しません。

通常の実行フローでは、生成・準備した試験ケースを人がレビューして承認してから実行します。承認済みケース、OpenAPI / scenarios.yaml、接続設定、テストデータを固定すれば、以後の実行と結果判定は自動化できます。OpenAPI やシナリオを変更した場合は再レビューが必要です。`--allow-draft` による未承認実行は探索用として区別されます。

したがって、完全自動化できるのは「確認済みの仕様と期待値を繰り返し実行すること」です。最初に OpenAPI が実装を正しく表しているか、DB mapping と業務上の期待値が正しいか、接続先が専用テスト環境かを決める作業は残ります。

初版の入力は、人が用意したOpenAPIまたはUIで編集した契約です。PHPからの自動抽出、大量データ・負荷試験、任意の業務ロジックの推定は初版の対象外です。

## 初版の検証記録

独立したAPI実装・故障注入・実ブラウザー・Windows起動経路の確認は [first-release-validation.md](first-release-validation.md) を参照してください。
