-- 試験実行前に流すSQL。試験に関係ない既存データを消し、
-- ID指定系の試験（GET/PUT/DELETE）が404にならないよう、最低限のダミーデータを仕込む。

TRUNCATE TABLE users RESTART IDENTITY CASCADE;

INSERT INTO users (id, name, email) VALUES
  (1, 'ダミー太郎', 'dummy@example.com');
