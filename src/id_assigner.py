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
    #
    # 生成したサフィックス（例: "op_2"）が、たまたま別の operation が本来持つ
    # operationId（例えば本当に "op_2" という operationId が別に存在する場合）と
    # 衝突すると、2つの無関係な operation が同じ試験IDプレフィックスの下に
    # 混ざってしまう。used_ids で既に確定した解決済みIDを追跡し、衝突する候補は
    # 使わないようにする。
    op_id_count: dict[str, int] = {}
    resolved_id_by_key: dict[tuple[str, str], str] = {}
    used_ids: set[str] = set()

    for tc in cases:
        key = (tc["path"], tc["method"])
        if key in resolved_id_by_key:
            continue
        raw_id = tc["operationId"]
        count = op_id_count.get(raw_id, 0)
        op_id_count[raw_id] = count + 1

        if count == 0 and raw_id not in used_ids:
            resolved = raw_id
        else:
            n = count + 1
            resolved = f"{raw_id}_{n}"
            while resolved in used_ids:
                n += 1
                resolved = f"{raw_id}_{n}"
            log.warn({"operationId": raw_id}, "operationId 重複 → サフィックス付与")

        resolved_id_by_key[key] = resolved
        used_ids.add(resolved)

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
