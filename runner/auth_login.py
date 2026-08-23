"""ログインAPIを呼び出してテスト用の認証トークンを取得する（runner.py の --auth-config）。

固定の TEST_AUTH_TOKEN 環境変数だけでは、ログインしてトークンを発行する方式の
APIに対応できないため、ログインAPIを1回呼び出してトークンを取得し、
以降の全リクエストに付与するヘッダとして使えるようにする。
"""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

CURL_TIMEOUT = 10


class AuthLoginError(Exception):
    pass


def load_auth_config(path: str) -> dict:
    """auth-config JSON を読み込み、必須キーを検証する。

    必須: login_url, method
    任意: body（ログインリクエストのJSONボディ）
          token_path（レスポンスJSON内のトークンの場所。ドット区切り。既定 "access_token"）
          header_name（付与するヘッダ名。既定 "Authorization"）
          header_format（トークンの埋め込み方。既定 "Bearer {token}"）
    """
    p = Path(path)
    if not p.exists():
        raise AuthLoginError(f"認証設定ファイルが見つかりません: {path}")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise AuthLoginError(f"認証設定ファイルのパースに失敗しました: {e}") from e

    if not isinstance(data, dict):
        raise AuthLoginError("認証設定ファイルの内容が不正です（オブジェクトである必要があります）")

    required = {"login_url", "method"}
    missing = required - set(data.keys())
    if missing:
        raise AuthLoginError(f"認証設定に必須キーが不足しています: {sorted(missing)}")

    return data


def perform_login(base_url: str, auth_config: dict) -> str:
    """ログインAPIを呼び出し、抽出したトークン文字列を返す。失敗時は AuthLoginError を送出する。"""
    url = base_url.rstrip("/") + auth_config["login_url"]
    method = str(auth_config.get("method", "POST")).upper()
    body = auth_config.get("body") or {}

    cmd = [
        "curl.exe", "-s", "-X", method,
        "-w", "\n%{http_code}",
        "--max-time", str(CURL_TIMEOUT),
        url,
    ]
    if body:
        cmd += ["-H", "Content-Type: application/json; charset=utf-8", "-d", json.dumps(body, ensure_ascii=False)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        raise AuthLoginError("curl.exe が見つかりません")

    if result.returncode != 0:
        raise AuthLoginError(f"ログインリクエストの実行に失敗しました: {result.stderr}")

    body_text, _, status_text = result.stdout.rpartition("\n")
    try:
        status = int(status_text.strip())
    except ValueError:
        raise AuthLoginError(f"curl の出力を解析できませんでした: {result.stdout!r}")

    if not (200 <= status < 300):
        raise AuthLoginError(f"ログインに失敗しました（ステータス {status}）: {body_text}")

    try:
        response_json = json.loads(body_text) if body_text.strip() else {}
    except json.JSONDecodeError:
        raise AuthLoginError(f"ログインレスポンスがJSONとして解析できません: {body_text!r}")

    token_path = auth_config.get("token_path", "access_token")
    token = _extract_token(response_json, token_path)
    if token is None:
        raise AuthLoginError(f"レスポンスからトークンを取得できませんでした（token_path={token_path!r}）")

    return str(token)


def _extract_token(response: object, token_path: str):
    node = response
    for part in token_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def build_auth_header(token: str, auth_config: dict) -> tuple[str, str]:
    """(ヘッダ名, ヘッダ値) を返す。"""
    header_name = auth_config.get("header_name", "Authorization")
    header_format = auth_config.get("header_format", "Bearer {token}")
    header_value = header_format.format(token=token)
    return header_name, header_value
