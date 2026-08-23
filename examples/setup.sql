-- 試験実行前に流すSQL。試験に関係ない既存データを消し、
-- ID指定系の試験（GET/PUT/DELETE）が404にならないよう、最低限のダミーデータを仕込む。
--
-- 複数テーブルにまたがる場合は、このファイルに文を並べて書けばよい（1本のSQLファイルの
-- 中で完結させる）。ただし外部キーで参照される側（親テーブル）を先に、参照する側
-- （子テーブル）を後に投入すること。TRUNCATEはCASCADEを付ければ参照関係を辿って
-- まとめて消せるが、親テーブルだけをTRUNCATE ... CASCADEすると子テーブルの行も
-- 巻き添えで消えるため、逆に子→親の順でTRUNCATEするほうが意図が分かりやすい。

-- 子テーブルから先にTRUNCATE（外部キー違反を避けるため）
TRUNCATE TABLE order_lines RESTART IDENTITY CASCADE;
TRUNCATE TABLE orders RESTART IDENTITY CASCADE;
TRUNCATE TABLE users RESTART IDENTITY CASCADE;

-- 親テーブルから先にINSERT
INSERT INTO users (id, name, email) VALUES
  (1, 'ダミー太郎', 'dummy@example.com');

INSERT INTO orders (id, user_id, status) VALUES
  (1, 1, 'pending');

INSERT INTO order_lines (id, order_id, product_name, quantity, price) VALUES
  (1, 1, 'ダミー商品', 1, 1000);

-- 【重要な制限】この --setup/--teardown の仕組みはPostgreSQLにのみ対応している。
-- InfluxDBはSQLではなくLine Protocolでデータを書き込むため、この仕組みでは
-- 初期データを仕込めない。InfluxDB側の試験データ準備は、別途スクリプトを
-- 用意するか、試験対象のAPI経由でデータを作成するなどの対応が必要。
