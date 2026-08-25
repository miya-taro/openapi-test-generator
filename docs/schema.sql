-- docs/mock_api.py が前提とするテーブル定義。
-- CI（.github/workflows/test.yml の e2e ジョブ）と、ローカルでの動作確認の両方で
-- 同じスキーマを使うための単一のソース。
--
-- 外部キー制約があるため、DROP は子テーブルから、CREATE は親テーブルから行う。

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS cart_items;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS categories;

CREATE TABLE categories (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE users (
    id    SERIAL PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT,
    role  TEXT NOT NULL DEFAULT 'member'
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT,
    price       NUMERIC NOT NULL DEFAULT 0,
    category_id INTEGER REFERENCES categories(id),
    status      TEXT NOT NULL DEFAULT 'draft'
);

CREATE TABLE orders (
    id      SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    status  TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE reviews (
    id         SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    rating     INTEGER,
    comment    TEXT
);

CREATE TABLE cart_items (
    id         SERIAL PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    quantity   INTEGER
);

CREATE TABLE order_items (
    id         SERIAL PRIMARY KEY,
    order_id   INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity   INTEGER
);
