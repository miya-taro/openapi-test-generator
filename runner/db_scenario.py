"""DBシナリオ（API呼び出し → DB検証）のYAML定義を読み込む。"""
from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml

try:
    from .db_backends.invariant_eval import literal_repr
except ImportError:  # direct `python runner/db_scenario_runner.py` execution
    from db_backends.invariant_eval import literal_repr

SUPPORTED_ENGINES = {"postgres", "influxdb"}
_PLACEHOLDER = re.compile(r"^\{\{\s*(\w+)\.([\w.]+)\s*\}\}$")
_EMBEDDED_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\.([\w.]+)\s*\}\}")
_SAFE_SCENARIO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SAFE_AUTH_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_SAFE_DB_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ScenarioError(Exception):
    pass


@dataclass
class GivenItem:
    """シナリオの前提データ（factory）。APIチェーン（{{response.xxx}}）だけでは、
    そもそも作成用のAPIエンドポイントが存在しないリソース（外部連携で作られるユーザー等）の
    前提データを用意できないため、DBに直接INSERTする経路として用意する。

    table に as で指定した名前を付け、request/db_check 側から
    `{{given.<as名>.<カラム名>}}` の形で参照する（生成された自動採番IDの参照等）。
    """
    table: str
    as_name: str
    fields: dict = field(default_factory=dict)


@dataclass
class ScenarioRequest:
    operation_id: str
    body: dict = field(default_factory=dict)
    path_params: dict = field(default_factory=dict)
    query_params: dict = field(default_factory=dict)


@dataclass
class DBCheck:
    engine: str
    expect: dict = field(default_factory=dict)
    # 不変条件（invariant）検証。「stockは注文数量ぶんだけ減っている」「stockは負にならない」
    # のような、絶対値ではなく関係性を検証する式のリスト（postgresのみ対応）。
    # `{{db.<カラム名>}}` で実測値、`{{given.xxx}}`/`{{response.xxx}}` で前提データ・
    # 直前のAPIレスポンスの値を参照できる。例: "{{db.stock}} == {{given.product_a.stock}} - 1"
    invariants: list[str] = field(default_factory=list)
    # postgres 用
    table: str | None = None
    where: dict | None = None
    raw_sql: str | None = None
    # influxdb 用
    measurement: str | None = None
    tags: dict | None = None
    time_range: str | None = None


@dataclass
class DBResponseFilter:
    """Map an API body/path/query parameter to a database comparison rule."""
    source: str
    parameter: str
    column: str
    operator: str
    auto: bool = True
    parameter_format: str | None = None
    group: str | None = None


@dataclass
class DBResponseCheck:
    """Derive an API response expectation from existing PostgreSQL rows."""
    table: str
    fields: dict[str, str] = field(default_factory=dict)  # response path -> DB column
    filters: list[DBResponseFilter] = field(default_factory=list)
    array_path: str | None = "$"


@dataclass
class ScenarioCleanup:
    """Delete only rows created by this POST call, identified by an explicit primary key."""
    table: str
    primary_key: str
    where: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseCheck:
    """APIレスポンス自体の内容を検証する（db_checkがDB側の状態を見るのに対し、
    こちらはAPI呼び出しの結果そのものを見る）。

    典型的な用途: DBに事前に極端な値（最大値・最小値等）を仕込んだ状態でGET系APIを呼び、
    レスポンスに正しい値が返ってくることを確認する（db_checkはAPI呼び出し後のDB変化を
    見る仕組みなので、こちらの用途には向かない）。
    """
    expect_status: int | None = None
    expect_body: dict = field(default_factory=dict)
    expect_contains: list[dict] = field(default_factory=list)
    expect_values: list[dict] = field(default_factory=list)


@dataclass
class DBScenario:
    name: str
    request: ScenarioRequest
    db_check: DBCheck | None = None
    response_check: ResponseCheck | None = None
    given: list[GivenItem] = field(default_factory=list)
    auth_profile: str | None = None
    scenario_id: str | None = None
    case_id_override: str | None = field(default=None, repr=False, compare=False)
    db_response_check: DBResponseCheck | None = None
    cleanup: ScenarioCleanup | None = None

    @property
    def case_id(self) -> str:
        """Return the stable ID shared by the master, reports, and reruns."""
        if self.case_id_override is not None:
            return self.case_id_override
        if self.scenario_id is not None:
            if not isinstance(self.scenario_id, str) or not _SAFE_SCENARIO_ID.fullmatch(self.scenario_id):
                raise ScenarioError(
                    f"シナリオ「{self.name}」のidは英数字、ドット、ハイフン、アンダースコアで指定してください"
                )
            return self.scenario_id if self.scenario_id.upper().startswith("DB-") else f"DB-{self.scenario_id}"

        canonical = json.dumps(
            self.case_definition(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12].upper()
        return f"DB-{digest}"

    def case_definition(self) -> dict:
        """Return the normalized, runtime-secret-free test definition."""
        request_definition = {
            "operationId": self.request.operation_id,
            "body": self.request.body,
            "pathParams": self.request.path_params,
        }
        if self.request.query_params:
            request_definition["queryParams"] = self.request.query_params
        definition = {
            "request": request_definition,
            "given": [
                {"table": item.table, "as": item.as_name, "fields": item.fields}
                for item in self.given
            ],
            "responseCheck": (
                {
                    "expectedStatus": self.response_check.expect_status,
                    "expectedBody": self.response_check.expect_body,
                    **({"expectedValues": self.response_check.expect_values}
                       if self.response_check.expect_values else {}),
                    **(
                        {"expectedContains": self.response_check.expect_contains}
                        if self.response_check.expect_contains else {}
                    ),
                }
                if self.response_check
                else None
            ),
            "dbCheck": (
                {
                    "engine": self.db_check.engine,
                    "expect": self.db_check.expect,
                    "invariants": self.db_check.invariants,
                    "table": self.db_check.table,
                    "where": self.db_check.where,
                    "rawSql": self.db_check.raw_sql,
                    "measurement": self.db_check.measurement,
                    "tags": self.db_check.tags,
                    "timeRange": self.db_check.time_range,
                }
                if self.db_check
                else None
            ),
        }
        if self.db_response_check:
            definition["dbResponseCheck"] = {
                "table": self.db_response_check.table,
                "fields": self.db_response_check.fields,
                "filters": [
                    {
                        "source": item.source,
                        "parameter": item.parameter,
                        "column": item.column,
                        "operator": item.operator,
                        "auto": item.auto,
                        "format": item.parameter_format,
                        **({"group": item.group} if item.group else {}),
                    }
                    for item in self.db_response_check.filters
                ],
                "arrayPath": self.db_response_check.array_path,
            }
        if self.cleanup:
            definition["cleanup"] = {
                "table": self.cleanup.table,
                "primaryKey": self.cleanup.primary_key,
                "where": self.cleanup.where,
            }
        if self.auth_profile is not None:
            definition["authProfile"] = self.auth_profile
        return definition


def load_scenarios(yaml_path: str | Path) -> list[DBScenario]:
    path = Path(yaml_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ScenarioError(f"ファイルの読み込みに失敗しました: {e}") from e
    return parse_scenarios(text)


def parse_scenarios(text: str) -> list[DBScenario]:
    """YAMLテキストからシナリオ一覧を組み立てる（load_scenariosのファイル読み込み無し版）。

    GUIの編集中プレビュー（未保存のテキスト）をファイルに書き出さずそのまま検証したい
    ケースのために分離している。
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ScenarioError(f"YAML のパースに失敗しました: {e}") from e

    if not isinstance(raw, dict) or "scenarios" not in raw:
        raise ScenarioError('YAML に "scenarios" キーがありません')

    scenarios_raw = raw["scenarios"]

    if isinstance(scenarios_raw, list):
        # 旧形式: scenarios が直接シナリオのリスト（後方互換のため維持）
        items = scenarios_raw
        defaults: dict = {}
    elif isinstance(scenarios_raw, dict):
        # 新形式: scenarios.defaults に共通の既定値、scenarios.list にシナリオのリスト。
        # 例えば同じファイル内で engine が全部同じ場合、シナリオごとに書かずに済む。
        if not isinstance(scenarios_raw.get("list"), list):
            raise ScenarioError('"scenarios.list" はリストである必要があります')
        items = scenarios_raw["list"]
        defaults = scenarios_raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ScenarioError('"scenarios.defaults" はオブジェクトである必要があります')
    else:
        raise ScenarioError('"scenarios" はリストまたは defaults/list を持つオブジェクトである必要があります')

    scenarios: list[DBScenario] = []
    for i, item in enumerate(items):
        try:
            scenarios.append(_parse_scenario(item, defaults))
        except (KeyError, TypeError) as e:
            raise ScenarioError(f"scenarios[{i}] の形式が不正です: {e}") from e

    seen: set[str] = set()
    occurrences: dict[str, int] = {}
    for scenario in scenarios:
        base_id = scenario.case_id
        occurrence = occurrences.get(base_id, 0) + 1
        occurrences[base_id] = occurrence
        case_id = base_id
        if case_id in seen:
            if scenario.scenario_id is not None:
                raise ScenarioError(f"DBシナリオの試験IDが重複しています: {case_id}")
            suffix = occurrence
            while case_id in seen:
                case_id = f"{base_id}-{suffix}"
                suffix += 1
            scenario.case_id_override = case_id
        seen.add(case_id)

    return scenarios


def _parse_scenario(raw: dict, defaults: dict) -> DBScenario:
    name = raw["name"]
    auth_profile = raw.get("auth_profile")
    if auth_profile is not None and (
        not isinstance(auth_profile, str) or not _SAFE_AUTH_PROFILE.fullmatch(auth_profile)
    ):
        raise ScenarioError(
            "auth_profile は英数字で始まる英数字・ドット・ハイフン・アンダースコアのプロファイル名で指定してください"
        )

    req_raw = raw["request"]
    request = ScenarioRequest(
        operation_id=req_raw["operationId"],
        body=req_raw.get("body") or {},
        path_params=req_raw.get("path_params") or {},
        query_params=req_raw.get("query_params") or {},
    )

    if not any(key in raw for key in ("db_check", "response_check", "db_response_check")):
        raise ScenarioError("db_check、response_check、db_response_check のいずれかは必須です")

    db_check = None
    if "db_check" in raw:
        check_raw = raw["db_check"]
        engine = check_raw.get("engine") or defaults.get("engine")
        if not engine:
            raise ScenarioError(
                "engine が指定されていません（db_check.engine か scenarios.defaults.engine のどちらかで指定してください）"
            )
        if engine not in SUPPORTED_ENGINES:
            raise ScenarioError(
                f"未対応の engine です: {engine!r}（対応: {', '.join(sorted(SUPPORTED_ENGINES))}）"
            )
        invariants_raw = check_raw.get("invariants") or []
        if not isinstance(invariants_raw, list) or not all(isinstance(v, str) for v in invariants_raw):
            raise ScenarioError("db_check.invariants は文字列のリストである必要があります")
        db_check = DBCheck(
            engine=engine,
            expect=check_raw.get("expect") or {},
            invariants=invariants_raw,
            table=check_raw.get("table"),
            where=check_raw.get("where"),
            raw_sql=check_raw.get("raw_sql"),
            measurement=check_raw.get("measurement"),
            tags=check_raw.get("tags"),
            time_range=check_raw.get("time_range"),
        )

    response_check = None
    if "response_check" in raw:
        resp_raw = raw["response_check"] or {}
        expect_raw = resp_raw.get("expect") or {}
        response_check = ResponseCheck(
            expect_status=expect_raw.get("status"),
            expect_body=expect_raw.get("body") or {},
            expect_contains=expect_raw.get("contains") or [],
            expect_values=expect_raw.get("values", []),
        )
        if not isinstance(response_check.expect_body, dict):
            raise ScenarioError("response_check.expect.body はオブジェクトである必要があります")
        if not isinstance(response_check.expect_contains, list):
            raise ScenarioError("response_check.expect.contains はリストである必要があります")
        if not isinstance(response_check.expect_values, list):
            raise ScenarioError("response_check.expect.values はリストである必要があります")
        seen_value_paths = set()
        for item in response_check.expect_values:
            if not isinstance(item, dict):
                raise ScenarioError("response_check.expect.values の各項目はオブジェクトにしてください")
            path = item.get("path")
            source = item.get("source")
            if not isinstance(path, str) or not path.strip() or path in seen_value_paths:
                raise ScenarioError("response_check.expect.values.path は重複のない項目パスにしてください")
            seen_value_paths.add(path)
            if not isinstance(source, str) or source not in {"body", "query", "path", "fixed"}:
                raise ScenarioError("response_check.expect.values.source は body、query、path、fixed にしてください")
            if source == "fixed":
                if "value" not in item:
                    raise ScenarioError("固定値の照合には value が必要です")
            elif not isinstance(item.get("parameter"), str) or not item["parameter"].strip():
                raise ScenarioError("送信値の照合には parameter が必要です")
            if item.get("when_missing", "error") not in ("error", "skip", "fixed"):
                raise ScenarioError("when_missing は error、skip、fixed のいずれかにしてください")
            if item.get("when_missing") == "fixed" and "value" not in item:
                raise ScenarioError("省略時の固定値には value が必要です")
            if item.get("comparison", "exact") not in ("exact", "date-time"):
                raise ScenarioError("comparison は exact または date-time にしてください")
        for i, expected_item in enumerate(response_check.expect_contains):
            if (
                not isinstance(expected_item, dict)
                or not isinstance(expected_item.get("fields"), dict)
                or not isinstance(expected_item.get("path", "$"), str)
            ):
                raise ScenarioError(
                    f"response_check.expect.contains[{i}] には文字列 path と fields オブジェクトが必要です"
                )

    db_response_check = None
    if "db_response_check" in raw:
        check_raw = raw["db_response_check"] or {}
        if not isinstance(check_raw, dict):
            raise ScenarioError("db_response_check はオブジェクトである必要があります")
        fields = check_raw.get("fields") or {}
        filters_raw = check_raw.get("filters") or []
        array_path = check_raw.get("array_path", "$")
        if not isinstance(check_raw.get("table"), str) or not check_raw["table"]:
            raise ScenarioError("db_response_check.table は必須です")
        if not isinstance(fields, dict) or not fields:
            raise ScenarioError("db_response_check.fields はレスポンス項目とDB列の対応を1件以上指定してください")
        if not all(isinstance(path, str) and path and isinstance(column, str) and column for path, column in fields.items()):
            raise ScenarioError("db_response_check.fields のキーと値は空でない文字列にしてください")
        if not isinstance(filters_raw, list):
            raise ScenarioError("db_response_check.filters はリストである必要があります")
        if array_path is not None and not isinstance(array_path, str):
            raise ScenarioError("db_response_check.array_path は文字列または null で指定してください")
        filters: list[DBResponseFilter] = []
        seen_params: set[tuple[str, str]] = set()
        for i, filter_raw in enumerate(filters_raw):
            if not isinstance(filter_raw, dict):
                raise ScenarioError(f"db_response_check.filters[{i}] はオブジェクトである必要があります")
            source = filter_raw.get("source", "query")
            parameter = filter_raw.get("parameter")
            column = filter_raw.get("column")
            operator = filter_raw.get("operator")
            auto = filter_raw.get("auto", True)
            parameter_format = filter_raw.get("format")
            group = filter_raw.get("group")
            if not isinstance(source, str) or source not in {"query", "path", "body"}:
                raise ScenarioError(f"db_response_check.filters[{i}].source は query、path、body のいずれかにしてください")
            if not all(isinstance(value, str) and value for value in (parameter, column)):
                raise ScenarioError(f"db_response_check.filters[{i}] に parameter と column が必要です")
            if not isinstance(operator, str) or operator not in {"=", ">", ">=", "<", "<=", "in"}:
                raise ScenarioError(f"db_response_check.filters[{i}].operator は =, >, >=, <, <=, in のいずれかにしてください")
            if not isinstance(auto, bool):
                raise ScenarioError(f"db_response_check.filters[{i}].auto は真偽値にしてください")
            if parameter_format is not None and not isinstance(parameter_format, str):
                raise ScenarioError(f"db_response_check.filters[{i}].format は文字列にしてください")
            if group is not None and (not isinstance(group, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", group)):
                raise ScenarioError(f"db_response_check.filters[{i}].group は英数字のグループ名にしてください")
            if source == "body" and auto:
                raise ScenarioError(f"db_response_check.filters[{i}].body は自動値生成に対応していません")
            if operator == "in" and auto:
                raise ScenarioError(f"db_response_check.filters[{i}].in は固定の配列値が必要です")
            param_key = (source, parameter)
            if param_key in seen_params:
                raise ScenarioError(f"db_response_check.filters[{i}] のAPIパラメータが重複しています: {source}.{parameter}")
            seen_params.add(param_key)
            filters.append(DBResponseFilter(source, parameter, column, operator, auto, parameter_format, group))
        db_response_check = DBResponseCheck(
            table=check_raw["table"], fields=fields, filters=filters, array_path=array_path,
        )

    cleanup = None
    if "cleanup" in raw:
        cleanup_raw = raw["cleanup"]
        if not isinstance(cleanup_raw, dict):
            raise ScenarioError("cleanup はオブジェクトである必要があります")
        table = cleanup_raw.get("table")
        primary_key = cleanup_raw.get("primary_key")
        where = cleanup_raw.get("where")
        if not isinstance(table, str) or not table:
            raise ScenarioError("cleanup.table は必須です")
        if not _SAFE_DB_IDENTIFIER.fullmatch(table):
            raise ScenarioError("cleanup.table は英字または_で始まる英数字・_で指定してください")
        if not isinstance(primary_key, str) or not primary_key:
            raise ScenarioError("cleanup.primary_key は必須です")
        if not _SAFE_DB_IDENTIFIER.fullmatch(primary_key):
            raise ScenarioError("cleanup.primary_key は英字または_で始まる英数字・_で指定してください")
        if not isinstance(where, dict) or not where:
            raise ScenarioError("cleanup.where は作成行を特定するDB列を1件以上指定してください")
        if not all(isinstance(key, str) and _SAFE_DB_IDENTIFIER.fullmatch(key) for key in where):
            raise ScenarioError("cleanup.where のDB列名は英字または_で始まる英数字・_で指定してください")
        if not all(value is None or isinstance(value, (str, int, float, bool)) for value in where.values()):
            raise ScenarioError("cleanup.where の値は文字列・数値・boolean・nullで指定してください")
        cleanup = ScenarioCleanup(table=table, primary_key=primary_key, where=where)

    given: list[GivenItem] = []
    for i, g in enumerate(raw.get("given") or []):
        if "table" not in g or "as" not in g:
            raise ScenarioError(f"given[{i}] には table と as が必須です")
        given.append(GivenItem(table=g["table"], as_name=g["as"], fields=g.get("fields") or {}))

    return DBScenario(
        name=name,
        request=request,
        db_check=db_check,
        response_check=response_check,
        db_response_check=db_response_check,
        given=given,
        auth_profile=auth_profile,
        scenario_id=raw.get("id"),
        cleanup=cleanup,
    )


def resolve_placeholders(value: Any, response: dict, given: dict | None = None) -> Any:
    """`{{response.xxx}}` および `{{given.<as名>.xxx}}` 形式のプレースホルダを解決する。

    response: 直前のシナリオのAPIレスポンス。given: このシナリオの前提データ
    （as名 -> factoryでINSERTされた行の辞書）。値全体がプレースホルダのみの場合は、
    元の型（int/float/bool等）を保持する。
    """
    if isinstance(value, str):
        m = _PLACEHOLDER.match(value.strip())
        if not m:
            return value
        namespace, path = m.group(1), m.group(2)
        if namespace == "response":
            root = response
        elif namespace == "given":
            root = given or {}
        else:
            raise ScenarioError(
                f"未対応のプレースホルダ名前空間です: '{namespace}'（response/given のみ対応）"
            )
        node: Any = root
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ScenarioError(f"'{namespace}.{path}' が見つかりません")
            node = node[part]
        return node

    if isinstance(value, dict):
        return {k: resolve_placeholders(v, response, given) for k, v in value.items()}

    if isinstance(value, list):
        return [resolve_placeholders(v, response, given) for v in value]

    return value


def resolve_invariant_expr(expr: str, response: dict, given: dict | None = None) -> str:
    """invariant式中の `{{response.xxx}}`/`{{given.xxx}}` を埋め込みで置換する。

    `resolve_placeholders` と違い、文字列全体が1個のプレースホルダである必要はない
    （"{{db.stock}} == {{given.product_a.stock}} - 1" のように式の一部として埋め込める）。
    `{{db.xxx}}`（DB実測値。行を取得するまで値が定まらない）はここでは解決せず、
    そのまま残す（db_backends側でSELECT結果を使って解決する）。
    """
    def _replace(m: re.Match) -> str:
        namespace, path = m.group(1), m.group(2)
        if namespace == "db":
            return m.group(0)
        if namespace == "response":
            root = response
        elif namespace == "given":
            root = given or {}
        else:
            raise ScenarioError(
                f"未対応のプレースホルダ名前空間です: '{namespace}'（response/given/db のみ対応）"
            )
        node: Any = root
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ScenarioError(f"'{namespace}.{path}' が見つかりません")
            node = node[part]
        return literal_repr(node)

    return _EMBEDDED_PLACEHOLDER.sub(_replace, expr)


def resolve_db_check(db_check: DBCheck, response: dict, given: dict | None = None) -> DBCheck:
    """db_check 内の where/tags/expect(columns/fields含む)/invariants のプレースホルダを
    レスポンス値・前提データで解決した新しい DBCheck を返す。"""
    return replace(
        db_check,
        where=resolve_placeholders(db_check.where, response, given) if db_check.where else db_check.where,
        tags=resolve_placeholders(db_check.tags, response, given) if db_check.tags else db_check.tags,
        expect=resolve_placeholders(db_check.expect, response, given) if db_check.expect else db_check.expect,
        invariants=[resolve_invariant_expr(inv, response, given) for inv in db_check.invariants],
    )
