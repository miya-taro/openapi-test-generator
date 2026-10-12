"""ログインAPIを呼び出してテスト用の認証トークンを取得する（runner.py の --auth-config）。

固定の TEST_AUTH_TOKEN 環境変数だけでは、ログインしてトークンを発行する方式の
APIに対応できないため、ログインAPIを1回呼び出してトークンを取得し、
以降の全リクエストに付与するヘッダとして使えるようにする。
"""
from __future__ import annotations
import re
from pathlib import Path

import requests
import yaml

if __package__:
    from .models import DEFAULT_REQUEST_TIMEOUT
else:
    from models import DEFAULT_REQUEST_TIMEOUT

REQUEST_TIMEOUT = DEFAULT_REQUEST_TIMEOUT
_AUTH_PROFILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")


class AuthLoginError(Exception):
    pass


def load_auth_config(path: str) -> dict:
    """auth-config ファイル（JSON または YAML）を読み込み、必須キーを検証する。

    必須: login_url, method
    任意: body（ログインリクエストのJSONボディ）
          token_path（レスポンスJSON内のトークンの場所。ドット区切り。既定 "access_token"）
          header_name（付与するヘッダ名。既定 "Authorization"）
          header_format（トークンの埋め込み方。既定 "Bearer {token}"）

    JSON は YAML の構文的な上位互換にあたるため、拡張子を問わず yaml.safe_load で
    読み込む（既存の .json ファイルもそのまま読める）。YAML形式にすると、対応している
    書き方のバリエーションをコメントで残しておける（examples/auth_config.yaml 参照）。
    """
    p = Path(path)
    if not p.exists():
        raise AuthLoginError(f"認証設定ファイルが見つかりません: {path}")

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise AuthLoginError(f"認証設定ファイルのパースに失敗しました: {e}") from e

    if not isinstance(data, dict):
        raise AuthLoginError("認証設定ファイルの内容が不正です（オブジェクトである必要があります）")

    required = {"login_url", "method"}
    missing = required - set(data.keys())
    if missing:
        raise AuthLoginError(f"認証設定に必須キーが不足しています: {sorted(missing)}")

    profiles = data.get("auth_profiles", {})
    if not isinstance(profiles, dict):
        raise AuthLoginError("認証プロファイルは名前とログインボディのオブジェクトで指定してください")
    for name, body in profiles.items():
        if not isinstance(name, str) or not _AUTH_PROFILE_NAME.fullmatch(name):
            raise AuthLoginError("認証プロファイル名は英数字で始まる英数字・ドット・ハイフン・アンダースコアにしてください")
        if not isinstance(body, dict):
            raise AuthLoginError(f"認証プロファイル「{name}」のログインボディはJSONオブジェクトで指定してください")

    return data


def auth_config_for_profile(auth_config: dict, profile_name: str | None) -> dict:
    """Return a login config with the selected named profile's body.

    Existing auth-config fields remain the shared login definition. ``auth_profiles``
    maps scenario-safe names to credential bodies and is never copied into the
    effective config passed to the login request.
    """
    config = {key: value for key, value in auth_config.items() if key != "auth_profiles"}
    if profile_name is None:
        return config

    profiles = auth_config.get("auth_profiles") or {}
    if profile_name not in profiles:
        raise AuthLoginError(f"認証プロファイル「{profile_name}」が設定に見つかりません")
    config["body"] = profiles[profile_name]
    return config


def perform_login(base_url: str, auth_config: dict, session: requests.Session | None = None) -> str:
    """ログインAPIを呼び出し、抽出したトークン文字列を返す。失敗時は AuthLoginError を送出する。

    session を指定すると、ログインレスポンスの Set-Cookie もその Session に保存される
    （--cookie-jar 使用時、以降の全リクエストで runner.py 側から同じ Session が使われるため、
    ログイン時点で発行されたセッションCookieも自動的に引き継がれる）。
    """
    url = base_url.rstrip("/") + auth_config["login_url"]
    method = str(auth_config.get("method", "POST")).upper()
    body = auth_config.get("body") or {}

    sender = session if session is not None else requests
    try:
        response = sender.request(method, url, json=body if body else None, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise AuthLoginError(f"ログインリクエストの実行に失敗しました: {e}（{url} に接続できませんでした）") from e

    status = response.status_code
    body_text = response.text

    if not (200 <= status < 300):
        # Authentication endpoints can echo submitted credentials or tokens in an
        # error response. Keep response bodies out of GUI logs and test reports.
        raise AuthLoginError(f"ログインに失敗しました（ステータス {status}）")

    try:
        response_json = response.json() if body_text.strip() else {}
    except ValueError as e:
        raise AuthLoginError("ログインレスポンスがJSONとして解析できません") from e

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


def mark_login_response_sensitive(openapi: dict | None, auth_config: dict) -> None:
    """Mark only the configured login token path for report redaction, not validation."""
    import copy
    from urllib.parse import urlsplit

    if not isinstance(openapi, dict):
        return
    path = urlsplit(auth_config['login_url']).path
    operation = openapi.get('paths', {}).get(path, {}).get(str(auth_config.get('method', 'POST')).lower(), {})
    operation['responses'] = copy.deepcopy(operation.get('responses', {}))
    for response in operation['responses'].values():
        for media in (response.get('content') or {}).values():
            schema = media.get('schema')
            if not isinstance(schema, dict):
                continue
            media['schema'] = copy.deepcopy(schema)
            node = media['schema']
            for key in auth_config.get('token_path', 'access_token').split('.'):
                if not isinstance(node, dict):
                    break
                node = node.get('properties', {}).get(key)
            if isinstance(node, dict):
                node['x-api-tester-sensitive'] = True
