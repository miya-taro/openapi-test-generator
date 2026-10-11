#!/usr/bin/env python3
"""docs/openapi.json に対応する簡易モックAPIサーバー（DBシナリオの動作確認用）。

実際にPostgreSQL（apitester_test）へ読み書きするため、db_scenario_runner.py の
db_check（「APIを呼んだ結果DBが期待通り変化したか」の検証）が意味のある結果を返す。
本番相当の実装ではなく、あくまでGUIの動作確認用。

起動:
    uvicorn docs.mock_api:app --host 0.0.0.0 --port 8080

前提: DB接続設定（GUI）と同じ接続情報（127.0.0.1:5432 / apitester_test / postgres / testpass123）。
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException

DB = dict(host="127.0.0.1", port=5432, dbname="apitester_test", user="postgres", password="testpass123")
_test_config = os.environ.get("OPENAPI_TEST_DB_CONFIG")
if _test_config:
    # The repeatable verification script points this fixture API at its disposable PostgreSQL
    # container. Normal manual use keeps the historical local defaults above.
    DB = json.loads(Path(_test_config).read_text(encoding="utf-8"))["postgres"]

app = FastAPI()


@contextmanager
def _conn():
    # psycopg2の接続自体をwith文で使うとcommit/rollbackだけでcloseされないため、
    # 明示的にcloseするcontextmanagerでラップする（さもないとリクエストのたびに
    # 接続がリークし、連続稼働でmax_connectionsに達する）。
    conn = psycopg2.connect(**DB)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _fetch_one(cur, table: str, row_id: int) -> dict:
    cur.execute(f"SELECT * FROM {table} WHERE id = %s", (row_id,))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{table} {row_id} not found")
    return dict(row)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login")
def login():
    # ダミー実装: 入力内容によらず固定トークンを返す。
    return {"access_token": "mock-token-123"}


@app.post("/auth/logout")
def logout():
    return {}


# ---------- users ----------

@app.get("/users")
def list_users():
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM users ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@app.post("/users")
def create_user(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO users (name, email, role) VALUES (%s, %s, %s) RETURNING *",
            (payload.get("name"), payload.get("email"), payload.get("role", "member")),
        )
        return dict(cur.fetchone())


@app.get("/users/{user_id}")
def get_user(user_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _fetch_one(cur, "users", user_id)


@app.put("/users/{user_id}")
def update_user(user_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE users SET name = COALESCE(%s, name), role = COALESCE(%s, role) WHERE id = %s RETURNING *",
            (payload.get("name"), payload.get("role"), user_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        return dict(row)


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return {}


@app.get("/users/{user_id}/orders")
def list_user_orders(user_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY id", (user_id,))
        return [dict(r) for r in cur.fetchall()]


# ---------- categories ----------

@app.get("/categories")
def list_categories():
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM categories ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@app.post("/categories")
def create_category(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("INSERT INTO categories (name) VALUES (%s) RETURNING *", (payload.get("name"),))
        return dict(cur.fetchone())


@app.get("/categories/{category_id}")
def get_category(category_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _fetch_one(cur, "categories", category_id)


@app.put("/categories/{category_id}")
def update_category(category_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE categories SET name = COALESCE(%s, name) WHERE id = %s RETURNING *",
            (payload.get("name"), category_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="category not found")
        return dict(row)


@app.delete("/categories/{category_id}")
def delete_category(category_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (category_id,))
        return {}


# ---------- products ----------

@app.get("/products")
def list_products():
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM products ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@app.post("/products")
def create_product(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO products (name, description, price, category_id, status) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING *",
            (
                payload.get("name"),
                payload.get("description"),
                payload.get("price", 0),
                payload.get("categoryId"),
                payload.get("status", "draft"),
            ),
        )
        return dict(cur.fetchone())


@app.get("/products/{product_id}")
def get_product(product_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _fetch_one(cur, "products", product_id)


@app.put("/products/{product_id}")
def update_product(product_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE products SET name = COALESCE(%s, name), price = COALESCE(%s, price), "
            "status = COALESCE(%s, status) WHERE id = %s RETURNING *",
            (payload.get("name"), payload.get("price"), payload.get("status"), product_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="product not found")
        return dict(row)


@app.delete("/products/{product_id}")
def delete_product(product_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
        return {}


# ---------- orders ----------

@app.get("/orders")
def list_orders():
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM orders ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@app.post("/orders")
def create_order(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO orders (user_id, status) VALUES (%s, %s) RETURNING *",
            (payload.get("userId"), "pending"),
        )
        order = dict(cur.fetchone())
        for item in payload.get("items") or []:
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s)",
                (order["id"], item.get("productId"), item.get("quantity")),
            )
        return order


@app.get("/orders/{order_id}")
def get_order(order_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _fetch_one(cur, "orders", order_id)


@app.patch("/orders/{order_id}")
def update_order_status(order_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE orders SET status = COALESCE(%s, status) WHERE id = %s RETURNING *",
            (payload.get("status"), order_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")
        return dict(row)


@app.delete("/orders/{order_id}")
def cancel_order(order_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("UPDATE orders SET status = 'cancelled' WHERE id = %s RETURNING *", (order_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")
        return dict(row)


@app.get("/orders/{order_id}/items")
def list_order_items(order_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM order_items WHERE order_id = %s ORDER BY id", (order_id,))
        return [dict(r) for r in cur.fetchall()]


@app.post("/orders/{order_id}/items")
def add_order_item(order_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, quantity) VALUES (%s, %s, %s) RETURNING *",
            (order_id, payload.get("productId"), payload.get("quantity")),
        )
        return dict(cur.fetchone())


# ---------- reviews ----------

@app.get("/reviews")
def list_reviews(productId: int | None = None):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if productId is not None:
            cur.execute("SELECT * FROM reviews WHERE product_id = %s ORDER BY id", (productId,))
        else:
            cur.execute("SELECT * FROM reviews ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


@app.post("/reviews")
def create_review(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO reviews (product_id, rating, comment) VALUES (%s, %s, %s) RETURNING *",
            (payload.get("productId"), payload.get("rating"), payload.get("comment")),
        )
        return dict(cur.fetchone())


@app.get("/reviews/{review_id}")
def get_review(review_id: int):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        return _fetch_one(cur, "reviews", review_id)


@app.delete("/reviews/{review_id}")
def delete_review(review_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM reviews WHERE id = %s", (review_id,))
        return {}


# ---------- cart ----------

@app.get("/cart")
def get_cart():
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM cart_items ORDER BY id")
        return {"items": [dict(r) for r in cur.fetchall()]}


@app.post("/cart/items")
def add_cart_item(payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO cart_items (product_id, quantity) VALUES (%s, %s) RETURNING *",
            (payload.get("productId"), payload.get("quantity")),
        )
        return dict(cur.fetchone())


@app.patch("/cart/items/{item_id}")
def update_cart_item(item_id: int, payload: dict):
    with _conn() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "UPDATE cart_items SET quantity = COALESCE(%s, quantity) WHERE id = %s RETURNING *",
            (payload.get("quantity"), item_id),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="cart item not found")
        return dict(row)


@app.delete("/cart/items/{item_id}")
def remove_cart_item(item_id: int):
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM cart_items WHERE id = %s", (item_id,))
        return {}
