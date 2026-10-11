# 公開RESTサービスの試験結果

## 状態

**2026-10-11 14:09 UTC：公開APIに18件を実送信し、18件すべて合格しました。**

| サービス | 実行 | 合格 | 不合格・通信エラー |
|---|---:|---:|---:|
| JSONPlaceholder | 7 | 7 | 0 |
| httpbin | 11 | 11 | 0 |

通常のプロキシ経由で両サービスからHTTP 200が返ることを確認し、TLS検証を有効にして実行しました。環境設定の表示だけでは実際の接続可否を確定できませんでした。

実測したstatusは200・201・204・400・401・404。ExcelとJUnitの件数・合否もHTTP結果と一致しました。今回の試験ではアプリケーションコードの追加修正は必要ありませんでした。

ケース別の実行日時・URL・method・期待status・実測status・合否は [public-rest-validation-results.json](public-rest-validation-results.json) に記録しています。試験に使用したコミットは `75585ee`。OpenAPI、仕様・結果Excel、JUnit、実リクエスト・レスポンスを含むJSON証跡も保存しています。

## 対象と18ケース

| 公開サービス | ケース | 件数 |
|---|---|---:|
| JSONPlaceholder | GET単一取得・フィルタ検索・存在しない対象の404 | 3 |
| JSONPlaceholder | POST作成・PUT置換・PATCH部分更新・DELETE | 4 |
| httpbin | POST/PUT/PATCH/DELETEのJSONエコー | 4 |
| httpbin | GET＋JSONボディ | 1 |
| httpbin | カスタムヘッダ・Cookie | 2 |
| httpbin | Bearerヘッダあり200・ヘッダなし401 | 2 |
| httpbin | 空の204・定義した400 | 2 |

日本語、入れ子オブジェクト、配列、booleanのfalse、null、小数を含む本文を送信し、エコーの内容一致まで検証します。API側が任意の入力を受け付けるサービスなので、独自に「不正な型を必ず拒否する」という仕様を追加しません。

JSONPlaceholderの更新は公式にシミュレーションされるため、DBへの永続化は検証しません。httpbinのBearerはヘッダ形式を確認する機能で、実在のトークンの有効期限・権限の検証ではありません。

これらは外部で公開運用されているテスト用APIです。ローカルに再現したAPIへの試験結果とは区別します。前回のPyPI/npm/crates.ioの実運用APIでのGET試験12件とは別の試験セットです。

## 実行

準備のみ（HTTP送信なし）：

```bash
python docs/run_public_rest_checks.py --output-dir .artifacts/public-rest
```

公開サービスに接続できる環境で実行：

```bash
python docs/run_public_rest_checks.py --execute --output-dir .artifacts/public-rest
```

通常のCIやpytestからは送信しません。明示実行時に18件を1秒以上間隔を空けて逐次送信し、OpenAPI・試験仕様Excel・結果Excel・JUnit・JSON証跡を保存します。`summary.json` の `mode`、`executed`、`passed` で準備と実測を区別します。

## 資料

- [JSONPlaceholder公式ガイド](https://jsonplaceholder.typicode.com/guide/)
- [ガイドのソース](https://github.com/typicode/jsonplaceholder/blob/master/public/guide.html)
- [httpbin公開サービス](https://httpbin.org/)
- [httpbinの実装とAPI定義](https://github.com/postmanlabs/httpbin/blob/master/httpbin/core.py)
