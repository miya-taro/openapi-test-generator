# 公開RESTサービスの試験準備

## 状態

**2026-10-11時点：18ケースの準備とリクエスト構築を確認。外部への送信は未実施です。**

このクラウド環境の許可済み通信先に `jsonplaceholder.typicode.com` と `httpbin.org` が含まれていません。既存設定を保ち、2ドメインを追加する環境設定案を保存しました。環境設定のレビュー・保存・公開後に接続を確認し、以下の試験を実行します。保存済み下書きは実行環境への適用を意味しません。

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

通信設定が反映された後：

```bash
python docs/run_public_rest_checks.py --execute --output-dir .artifacts/public-rest
```

通常のCIやpytestからは送信しません。明示実行時に18件を1秒以上間隔を空けて逐次送信し、OpenAPI・試験仕様Excel・結果Excel・JUnit・JSON証跡を保存します。`summary.json` の `mode`、`executed`、`passed` で準備と実測を区別します。

## 資料

- [JSONPlaceholder公式ガイド](https://jsonplaceholder.typicode.com/guide/)
- [ガイドのソース](https://github.com/typicode/jsonplaceholder/blob/master/public/guide.html)
- [httpbin公開サービス](https://httpbin.org/)
- [httpbinの実装とAPI定義](https://github.com/postmanlabs/httpbin/blob/master/httpbin/core.py)
