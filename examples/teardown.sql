-- 試験実行後に流すSQL（失敗しても後続処理には影響しない）。
-- 試験で作成されたデータを片付ける。

TRUNCATE TABLE users RESTART IDENTITY CASCADE;
