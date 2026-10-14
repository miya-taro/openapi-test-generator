"""DBシナリオの response_check（APIレスポンス自体の内容検証）を実行する。

db_check がAPI呼び出し後のDB側の状態を見るのに対し、こちらはAPI呼び出しの結果
（ステータスコード・レスポンスボディ）そのものを期待値と突き合わせる。
"""
from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re
from uuid import UUID

from rfc3339_validator import validate_rfc3339

from db_scenario import ResponseCheck

_MISSING = object()


def check(response_check: ResponseCheck, status: int, response_json,
          request: dict | None = None, evidence: list | None = None) -> tuple[bool, str]:
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

    for rule in response_check.expect_values:
        path = rule["path"]
        source = rule["source"]
        actual = _get_nested(response_json, path)
        expected = rule["value"] if source == "fixed" else _get_nested(
            (request or {}).get(source, {}), rule["parameter"]
        )
        if expected is _MISSING and rule.get("when_missing") == "fixed":
            expected = rule["value"]
        detail = ""
        verdict = "OK"
        if expected is _MISSING:
            if rule.get("when_missing", "error") == "skip":
                verdict = "対象外"
                detail = "設定に従い、送信項目の省略時は値の照合を行いません"
            else:
                verdict = "NG"
                detail = "期待値に使う送信項目がありません"
        elif actual is _MISSING:
            verdict = "NG"
            detail = "レスポンスに項目がありません"
        elif not _value_matches(actual, expected, rule.get("comparison", "exact")):
            verdict = "NG"
            detail = "期待値と一致しません"
        if evidence is not None:
            evidence.append({"path": path, "source": source, "parameter": rule.get("parameter"),
                             "comparison": rule.get("comparison", "exact"), "verdict": verdict,
                             "expected": "[MISSING]" if expected is _MISSING else expected,
                             "actual": "[MISSING]" if actual is _MISSING else actual, "detail": detail})
        if verdict == "NG":
            mismatches.append(f"{path}: {detail}")

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

    for rule in response_check.collections:
        try:
            actual_rows = _collection_rows(response_json, rule['path'])
            projected = [{field: _get_nested(row, field) for field in rule['fields']} for row in actual_rows]
            remaining = list(projected)
            missing = []
            for expected in rule['rows']:
                index = next((i for i, actual in enumerate(remaining) if all(
                    actual[field] is not _MISSING and _value_matches(actual[field], expected[field], 'exact')
                    for field in rule['fields'])), None)
                if index is None:
                    missing.append(expected)
                else:
                    remaining.pop(index)
            ok = not missing and not remaining
            detail = '' if ok else f'期待行の欠落={len(missing)}件、余分・重複・値違い={len(remaining)}件'
            if evidence is not None:
                evidence.append({'path': rule['path'], 'source': 'fixed-collection', 'verdict': 'OK' if ok else 'NG',
                                 'expected': rule['rows'], 'actual': [
                                     {k: '[MISSING]' if v is _MISSING else v for k, v in row.items()} for row in projected], 'detail': detail})
            if not ok:
                mismatches.append(f"{rule['path']}: {detail}")
        except ValueError as exc:
            mismatches.append(str(exc))

    if mismatches:
        return False, "; ".join(mismatches)
    return True, ""


def _collection_rows(body, path):
    nodes = [body]
    if path == '$':
        if not isinstance(body, list):
            raise ValueError('レスポンス全体が配列ではありません')
        return body
    parts = path.split('.')
    for index, part in enumerate(parts):
        expand = part.endswith('[]') or index == len(parts)-1
        key = part[:-2] if part.endswith('[]') else part
        result = []
        for node in nodes:
            value = node.get(key, _MISSING) if isinstance(node, dict) else _MISSING
            if value is _MISSING:
                raise ValueError(f'{path}: レスポンスに項目がありません')
            if expand:
                if not isinstance(value, list):
                    raise ValueError(f'{path}: 配列ではありません')
                result.extend(value)
            else:
                result.append(value)
        nodes = result
    return nodes


def _value_matches(actual, expected, comparison):
    if comparison == "date-time":
        if not all(isinstance(value, str) and validate_rfc3339(value.upper()) for value in (actual, expected)):
            return False
        return _datetime_instant(actual) == _datetime_instant(expected)
    # JSON booleans must not equal numeric 0/1; integer/number are both JSON numbers.
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if type(actual) is not type(expected) and not (
        isinstance(actual, (int, float)) and isinstance(expected, (int, float))
    ):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(_value_matches(actual[k], v, "exact") for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(_value_matches(a, e, "exact") for a, e in zip(actual, expected, strict=True))
    return actual == expected


def _datetime_instant(value):
    fraction = re.search(r"\.(\d+)", value)
    parsed = datetime.fromisoformat(re.sub(r"\.\d+", "", value.upper()).replace("Z", "+00:00"))
    seconds = parsed.toordinal() * 86400 + parsed.hour * 3600 + parsed.minute * 60 + parsed.second
    seconds -= int(parsed.utcoffset().total_seconds())
    # Keep arbitrary RFC 3339 fractional precision instead of truncating to microseconds.
    return seconds, Decimal("0." + fraction[1]) if fraction else Decimal(0)


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
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    from db_backends.influx_response import InfluxTimestamp
    if isinstance(expected, InfluxTimestamp):
        return _value_matches(actual, str(expected), "date-time")
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
