-- 試験実行後に流すSQL（失敗しても後続処理には影響しない）。
-- 試験で作成されたデータを片付ける。複数テーブルの場合は、setup.sql と同様に
-- 子テーブルから先にTRUNCATEすること。

TRUNCATE TABLE order_lines RESTART IDENTITY CASCADE;
TRUNCATE TABLE orders RESTART IDENTITY CASCADE;
TRUNCATE TABLE users RESTART IDENTITY CASCADE;
