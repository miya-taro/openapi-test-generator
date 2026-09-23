# PHP（フレームワーク無し）のAPIを openapi.json 化する

`runner/`（Layer1/Layer2）はテスト対象APIの実装言語を問わない。素のPHPでOpenAPI定義がない場合は、まずVS CodeのGitHub CopilotにローカルのPHPコードを調べさせて下書きを作る。ソースをGitHubリポジトリへ登録する必要はない。Copilotに対象コードを読ませることは社内で許可されている前提とする。

1. VS Codeで対象のPHPプロジェクトを開く。
2. api-testerの「対象を登録」→「openapi.jsonがない場合（素のPHP）」を開き、「Copilot用の依頼文をコピー」を押す。
3. Copilot Chatに貼り付け、`openapi.draft.json`、`openapi.review.md`、`openapi.db-evidence.json`を作らせる。
4. `openapi.review.md`の根拠・要確認事項と下書きを人が確認し、必要な修正をする。
5. GUIで下書きを選び、検証結果を確認してから試験対象に設定する。Base URLと実行対象のAPIも確認する。
6. PostgreSQLの対応表候補を生成するときは、「DB準備」→「APIとDBテーブルの対応表を生成」の任意欄で`openapi.db-evidence.json`を選ぶ。ツールはoperationIdとDBテーブル・カラム名を照合し、根拠ファイル・行をmapping.yamlのコメントへ残す。

JSON形式: [`php-db-evidence.schema.json`](php-db-evidence.schema.json)。

DB根拠JSONがDBスキーマと一致しても確信度は「中」のままです。CopilotのSQL解釈や実行経路が正しいことまでは機械的に保証できないため、PHPソースと生成されたmapping.yamlをレビューしてください。JSONに複数テーブル候補がある場合やDBと不一致がある場合は、自動選択せず「低」確信度または未解決候補として出力します。

この導線はCopilotの自動呼び出しを必要としない。実際のPHPソースを使った抽出精度の評価は別途行う。

## Copilotの抽出精度を試す

実案件のコードを使う前に、[`examples/php-copilot-eval/README.md`](../examples/php-copilot-eval/README.md) の合成PHPサンプルで一度評価できる。サンプルにはルーティング、クエリ・JSON入力、入力検証、DBアクセス、成功・エラー応答を含め、期待するOpenAPIと採点表を添えている。Copilotが生成した草案を期待値と照合し、どの種類の情報を取りこぼすかを確認する。

これはCopilotが実案件でも同じ精度を出す保証ではない。実案件ごとにルーティング方式や共通処理が異なるため、最終的な評価には匿名化した実コードが必要になる。

## 前提: フレームワーク別の推奨

| 環境 | 推奨ツール | 自動導出の度合い |
|---|---|---|
| Laravel | [Scramble](https://scramble.dedoc.co/) | 高い（ルーティング・FormRequest等をリフレクションで読む。属性の手書き不要） |
| Laravel（代替） | Laravel API Inspector | 高い（FormRequestのバリデーションルールから直接生成） |
| **フレームワーク無し（素のPHP）** | **GitHub Copilotで下書き、api-testerで検証・確認** | **実装とCopilotの読める範囲に依存** |

素のPHPには「ルーティングテーブル」や「宣言的なバリデーション定義」という、自動導出の
情報源になりうる仕組みがフレームワークほど整っていないため、Laravel向けツールのような
完全自動導出はできない。長期的にPHPコード内で仕様を管理したい場合は、下記のswagger-php方式も選べる。

## 別案: swagger-phpのセットアップ

```sh
composer require --dev zircote/swagger-php
```

各エンドポイントのハンドラ関数（またはルーティングを振り分けているファイル）の直前に、
PHP 8 属性でリクエスト/レスポンスのスキーマを記述する。

```php
<?php
use OpenApi\Attributes as OA;

#[OA\Post(
    path: "/users",
    requestBody: new OA\RequestBody(
        required: true,
        content: new OA\JsonContent(
            required: ["name", "email"],
            properties: [
                new OA\Property(property: "name", type: "string", maxLength: 255),
                new OA\Property(property: "email", type: "string", format: "email"),
            ]
        )
    ),
    responses: [
        new OA\Response(response: 201, description: "Created", content: new OA\JsonContent(
            properties: [
                new OA\Property(property: "id", type: "integer"),
                new OA\Property(property: "name", type: "string"),
            ]
        )),
        new OA\Response(response: 400, description: "Validation error"),
    ]
)]
function handleCreateUser(): void {
    // 実装本体
}
```

PHP 7系（属性が使えない）の場合は、代わりにdocblockアノテーション形式（`@OA\Post(...)`）で
同じ内容を書ける（swagger-phpは両方式に対応）。

## openapi.json を生成する

```sh
vendor/bin/openapi src/ -o openapi.json
```
（`src/`は属性を書いたPHPファイルが置かれているディレクトリに読み替える。生成物をapi-testerへ渡す。）

## 一番の弱点: 属性と実装のドリフト

これは属性を人力で書く方式なので、**実装を直しても属性の更新を忘れる**というリスクが
構造的に残る（フレームワークのFormRequestのような「単一の情報源」が素のPHPには無いため）。

このリスクを完全には防げないが、生成した`openapi.json`に対してapi-testerのLayer1試験をローカルで実行し、宣言と実際のレスポンスの型・構造の食い違いを調べられる。仕様に書かれていないAPIや業務上の正しさはこれだけでは検出できないため、ソースと根拠資料のレビューも必要。

## api-testerへ渡す

レビュー済みの`openapi.json`をGUIの対象として設定する。試験の実行方法は、対象APIの実装言語がPythonでもPHPでも同じ。
