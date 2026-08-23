"""DBシナリオ（API呼び出し → DB検証）のYAML定義を読み込む。"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_ENGINES = {"postgres", "influxdb"}
_PLACEHOLDER = re.compile(r"^\{\{\s*response\.([\w.]+)\s*\}\}$")


class ScenarioError(Exception):
    pass


@dataclass
class ScenarioRequest:
    operation_id: str
    body: dict = field(default_factory=dict)
    path_params: dict = field(default_factory=dict)


@dataclass
class DBCheck:
    engine: str
    expect: dict = field(default_factory=dict)
    # postgres 用
    table: str | None = None
    where: dict | None = None
    raw_sql: str | None = None
    # influxdb 用
    measurement: str | None = None
    tags: dict | None = None
    time_range: str | None = None


@dataclass
class DBScenario:
    name: str
    request: ScenarioRequest
    db_check: DBCheck


def load_scenarios(yaml_path: str | Path) -> list[DBScenario]:
    path = Path(yaml_path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ScenarioError(f"YAML のパースに失敗しました: {e}") from e

    if not isinstance(raw, dict) or "scenarios" not in raw:
        raise ScenarioError('YAML に "scenarios" キーがありません')

    scenarios_raw = raw["scenarios"]
    if not isinstance(scenarios_raw, list):
        raise ScenarioError('"scenarios" はリストである必要があります')

    scenarios: list[DBScenario] = []
    for i, item in enumerate(scenarios_raw):
        try:
            scenarios.append(_parse_scenario(item))
        except (KeyError, TypeError) as e:
            raise ScenarioError(f"scenarios[{i}] の形式が不正です: {e}") from e

    return scenarios


def _parse_scenario(raw: dict) -> DBScenario:
    name = raw["name"]

    req_raw = raw["request"]
    request = ScenarioRequest(
        operation_id=req_raw["operationId"],
        body=req_raw.get("body") or {},
        path_params=req_raw.get("path_params") or {},
    )

    check_raw = raw["db_check"]
    engine = check_raw["engine"]
    if engine not in SUPPORTED_ENGINES:
        raise ScenarioError(
            f"未対応の engine です: {engine!r}（対応: {', '.join(sorted(SUPPORTED_ENGINES))}）"
        )

    db_check = DBCheck(
        engine=engine,
        expect=check_raw.get("expect") or {},
        table=check_raw.get("table"),
        where=check_raw.get("where"),
        raw_sql=check_raw.get("raw_sql"),
        measurement=check_raw.get("measurement"),
        tags=check_raw.get("tags"),
        time_range=check_raw.get("time_range"),
    )

    return DBScenario(name=name, request=request, db_check=db_check)


def resolve_placeholders(value: Any, response: dict) -> Any:
    """`{{response.xxx}}` 形式のプレースホルダを API レスポンス JSON の値に置き換える。

    値全体がプレースホルダのみの場合は、レスポンス側の元の型（int/float/bool等）を保持する。
    """
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value.strip())
        if not m:
            return value
        path = m.group(1).split(".")
        node: Any = response
        for part in path:
            if not isinstance(node, dict) or part not in node:
                raise ScenarioError(f"APIレスポンスに '{m.group(1)}' が見つかりません")
            node = node[part]
        return node

    if isinstance(value, dict):
        return {k: resolve_placeholders(v, response) for k, v in value.items()}

    if isinstance(value, list):
        return [resolve_placeholders(v, response) for v in value]

    return value


def resolve_db_check(db_check: DBCheck, response: dict) -> DBCheck:
    """db_check 内の where/tags/expect(columns/fields含む) のプレースホルダを
    レスポンス値で解決した新しい DBCheck を返す。"""
    return replace(
        db_check,
        where=resolve_placeholders(db_check.where, response) if db_check.where else db_check.where,
        tags=resolve_placeholders(db_check.tags, response) if db_check.tags else db_check.tags,
        expect=resolve_placeholders(db_check.expect, response) if db_check.expect else db_check.expect,
    )
