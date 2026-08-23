"""試験IDの採番（TC-{operationId}-{seq}）。"""
from __future__ import annotations

from . import logger as log

_SORT_ORDER_IN = {"path": 0, "query": 1, "header": 2, "cookie": 3, "body": 4}


def assign_ids(cases: list[dict]) -> list[dict]:
    # (path, method) の組を1つの「論理オペレーション」とみなし、
    # 同じ operationId 文字列が異なる (path, method) にまたがって出現した場合
    # （operationId の衝突）にのみ _2, _3 サフィックスを付与する。
    # 同一オペレーションから生成された複数のテストケースが同じ operationId を
    # 持つのは正常であり、衝突扱いしない。
    op_id_count: dict[str, int] = {}
    resolved_id_by_key: dict[tuple[str, str], str] = {}

    for tc in cases:
        key = (tc["path"], tc["method"])
        if key in resolved_id_by_key:
            continue
        raw_id = tc["operationId"]
        count = op_id_count.get(raw_id, 0)
        op_id_count[raw_id] = count + 1
        if count == 0:
            resolved_id_by_key[key] = raw_id
        else:
            resolved_id_by_key[key] = f"{raw_id}_{count + 1}"
            log.warn({"operationId": raw_id}, "operationId 重複 → サフィックス付与")

    # 解決済み operationId ごとにグルーピング → ソート → 連番付与
    groups: dict[str, list[dict]] = {}
    for tc in cases:
        resolved_op_id = resolved_id_by_key[(tc["path"], tc["method"])]
        groups.setdefault(resolved_op_id, []).append(tc)

    result: list[dict] = []

    for resolved_op_id, group in groups.items():

        def sort_key(tc: dict) -> tuple[int, str, int]:
            in_diff = _SORT_ORDER_IN.get(tc["in"], 9)
            is_abnormal = 1 if tc["perspective"].startswith("異常系") else 0
            return (in_diff, tc["paramName"], is_abnormal)

        sorted_group = sorted(group, key=sort_key)

        for idx, tc in enumerate(sorted_group):
            seq = str(idx + 1).zfill(3)
            result.append({**tc, "id": f"TC-{resolved_op_id}-{seq}"})

    return result
