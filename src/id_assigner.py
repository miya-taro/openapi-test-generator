"""試験IDの採番（TC-{operationId}-{seq}）。"""
from __future__ import annotations

from . import logger as log

_SORT_ORDER_IN = {"path": 0, "query": 1, "header": 2, "cookie": 3, "body": 4}


def assign_ids(cases: list[dict]) -> list[dict]:
    # operationId の重複を検出して _2, _3 サフィックスを付与
    op_id_count: dict[str, int] = {}
    op_id_map: dict[str, str] = {}

    for tc in cases:
        raw_id = tc["operationId"]
        if raw_id not in op_id_map:
            count = op_id_count.get(raw_id, 0)
            op_id_count[raw_id] = count + 1
            if count == 0:
                op_id_map[raw_id] = raw_id
            else:
                op_id_map[raw_id] = f"{raw_id}_{count + 1}"
                log.warn({"operationId": raw_id}, "operationId 重複 → サフィックス付与")

    # operationId ごとにグルーピング → ソート → 連番付与
    groups: dict[str, list[dict]] = {}
    for tc in cases:
        groups.setdefault(tc["operationId"], []).append(tc)

    result: list[dict] = []

    for op_id, group in groups.items():
        resolved_op_id = op_id_map.get(op_id, op_id)

        def sort_key(tc: dict) -> tuple[int, str, int]:
            in_diff = _SORT_ORDER_IN.get(tc["in"], 9)
            is_abnormal = 1 if tc["perspective"].startswith("異常系") else 0
            return (in_diff, tc["paramName"], is_abnormal)

        sorted_group = sorted(group, key=sort_key)

        for idx, tc in enumerate(sorted_group):
            seq = str(idx + 1).zfill(3)
            result.append({**tc, "id": f"TC-{resolved_op_id}-{seq}"})

    return result
