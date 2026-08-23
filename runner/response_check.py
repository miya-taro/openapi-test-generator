"""DBシナリオの response_check（APIレスポンス自体の内容検証）を実行する。

db_check がAPI呼び出し後のDB側の状態を見るのに対し、こちらはAPI呼び出しの結果
（ステータスコード・レスポンスボディ）そのものを期待値と突き合わせる。
"""
from __future__ import annotations

from db_scenario import ResponseCheck

_MISSING = object()


def check(response_check: ResponseCheck, status: int, response_json: dict) -> tuple[bool, str]:
    """response_check を実行し (適合したか, 詳細メッセージ) を返す。"""
    mismatches: list[str] = []

    if response_check.expect_status is not None and status != response_check.expect_status:
        mismatches.append(f"status: 期待={response_check.expect_status} 実測={status}")

    for path, expected_val in response_check.expect_body.items():
        actual_val = _get_nested(response_json, path)
        if actual_val is _MISSING:
            mismatches.append(f"{path}: レスポンスにフィールドが存在しません")
        elif actual_val != expected_val:
            mismatches.append(f"{path}: 期待={expected_val!r} 実測={actual_val!r}")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""


def _get_nested(response_json: dict, dotted_path: str):
    """ドット区切りのパス（例: "user.name"、配列要素は "items.0.price"）で
    レスポンスJSON内の値を辿る。見つからない場合は _MISSING を返す。"""
    node = response_json
    for part in dotted_path.split("."):
        if isinstance(node, list):
            if not part.isdigit() or int(part) >= len(node):
                return _MISSING
            node = node[int(part)]
        elif isinstance(node, dict):
            if part not in node:
                return _MISSING
            node = node[part]
        else:
            return _MISSING
    return node
