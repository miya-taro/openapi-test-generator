-- setup: テストデータを初期化する
TRUNCATE users RESTART IDENTITY CASCADE;
INSERT INTO users (name, email) VALUES ('テストユーザー', 'test@example.com');
