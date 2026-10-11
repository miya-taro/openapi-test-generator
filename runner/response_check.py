"""DBシナリオの response_check（APIレスポンス自体の内容検証）を実行する。

db_check がAPI呼び出し後のDB側の状態を見るのに対し、こちらはAPI呼び出しの結果
（ステータスコード・レスポンスボディ）そのものを期待値と突き合わせる。
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID

from db_scenario import ResponseCheck

_MISSING = object()


def check(response_check: ResponseCheck, status: int, response_json) -> tuple[bool, str]:
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

    for i, expected_item in enumerate(response_check.expect_contains):
        path = expected_item.get("path", "$")
        collection = response_json if path in ("", "$") else _get_nested(response_json, path)
        fields = expected_item["fields"]
        if collection is _MISSING:
            mismatches.append(f"contains[{i}]: {path} がレスポンスに存在しません")
            continue
        if not isinstance(collection, list):
            mismatches.append(f"contains[{i}]: {path} は配列ではありません")
            continue
        if not any(
            isinstance(item, (dict, list))
            and all(_get_nested(item, field_path) == expected for field_path, expected in fields.items())
            for item in collection
        ):
            mismatches.append(f"contains[{i}]: {path} に期待する項目が見つかりません ({fields!r})")

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""


def check_db_rows(
    db_response_check, response_json, expected_rows: list[dict], evidence: dict | None = None,
) -> tuple[bool, str]:
    """Compare a response collection/object with the exact rows selected from the DB.

    Ordering is ignored because an API's order is not part of its contract unless separately
    declared. Multiplicity and mapped values are exact: missing and extra records both fail.
    """
    array_path = db_response_check.array_path
    collection = response_json if array_path in ("", "$", None) else _get_nested(response_json, array_path)
    if collection is _MISSING:
        return False, f"DB照合: レスポンスに「{array_path}」がありません"

    if array_path is None:
        actual_rows = [collection]
        if not isinstance(collection, dict):
            return False, "DB照合: 単一オブジェクトを期待しましたが、レスポンスがオブジェクトではありません"
    else:
        if not isinstance(collection, list):
            return False, f"DB照合: 「{array_path}」は配列ではありません"
        actual_rows = collection

    if evidence is not None:
        evidence["actual_rows"] = [
            {path: _get_nested(row, path) if _get_nested(row, path) is not _MISSING else "[MISSING]"
             for path in db_response_check.fields}
            if isinstance(row, dict) else row
            for row in actual_rows
        ]
        evidence["expected_count"] = len(expected_rows)
        evidence["actual_count"] = len(actual_rows)

    remaining = list(actual_rows)
    missing: list[dict] = []
    for expected in expected_rows:
        match_index = next(
            (
                index for index, actual in enumerate(remaining)
                if isinstance(actual, dict)
                and all(
                    _response_value_matches(_get_nested(actual, path), expected_value)
                    for path, expected_value in expected.items()
                )
            ),
            None,
        )
        if match_index is None:
            missing.append(expected)
        else:
            remaining.pop(match_index)

    if missing or remaining:
        parts = []
        if missing:
            parts.append(f"DBにあるのにレスポンスにない行={len(missing)}件（例: {missing[0]!r}）")
        if remaining:
            parts.append(f"DB条件にないレスポンス行={len(remaining)}件")
        return False, "DB照合: " + "; ".join(parts)
    return True, ""


def _response_value_matches(actual, expected) -> bool:
    if actual is _MISSING:
        return False
    if isinstance(expected, Decimal):
        try:
            return Decimal(str(actual)) == expected
        except (InvalidOperation, ValueError, TypeError):
            return actual == expected
    if isinstance(expected, datetime) and isinstance(actual, str):
        try:
            parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
            return parsed == expected
        except ValueError:
            return False
    if isinstance(expected, date) and not isinstance(expected, datetime) and isinstance(actual, str):
        try:
            return date.fromisoformat(actual) == expected
        except ValueError:
            return False
    if isinstance(expected, time) and isinstance(actual, str):
        try:
            return time.fromisoformat(actual.replace("Z", "+00:00")) == expected
        except ValueError:
            return False
    if isinstance(expected, UUID):
        return str(actual).lower() == str(expected).lower()
    return actual == expected


def _get_nested(response_json, dotted_path: str):
    """ドット区切りのパス（例: "user.name"、配列要素は "items.0.price"）で
    レスポンスJSON内の値を辿る。見つからない場合は _MISSING を返す。"""
    if dotted_path in ("", "$", "."):
        return response_json
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
