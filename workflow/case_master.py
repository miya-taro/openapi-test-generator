"""Versioned adapters for the shared, reviewable test-case master."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.parser import parse_openapi



class CaseMasterError(ValueError):
    """Case master cannot be safely built from its configured sources."""


def _load_scenarios(path: Path):
    """Reuse the existing script-oriented parser without shadowing runner.py."""
    runner_dir = str(Path(__file__).resolve().parent.parent / "runner")
    inserted = runner_dir not in sys.path
    if inserted:
        sys.path.insert(0, runner_dir)
    try:
        from db_scenario import load_scenarios

        return load_scenarios(path)
    finally:
        if inserted:
            sys.path.remove(runner_dir)


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
_REVIEW_STATES = {"draft", "reviewed", "approved"}
_REVIEW_TRANSITIONS = {
    "draft": {"draft", "reviewed"},
    "reviewed": {"draft", "reviewed", "approved"},
    "approved": {"draft", "reviewed", "approved"},
}
_RUN_DIRECTORY = re.compile(r"^\d{8}-\d{6}-[a-f0-9]{8}$")


def _definition_hash(case: dict) -> str:
    definition = {
        key: case.get(key)
        for key in ("caseId", "kind", "title", "source", "definition", "expected")
    }
    canonical = json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CaseMasterError(f"入力ファイルを読み込めません: {path}: {exc}") from exc


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent, delete=False,
            prefix=f".{path.name}.", suffix=".tmp",
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(payload)
        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise CaseMasterError(f"ファイルを保存できません: {exc}") from exc


def _review_registry_path(master_path: Path) -> Path:
    root = master_path.parent.parent if _RUN_DIRECTORY.fullmatch(master_path.parent.name) else master_path.parent
    return root / "case-reviews.json"


def _operation_index(openapi_path: Path) -> dict[str, dict[str, str]]:
    try:
        api = parse_openapi(str(openapi_path))
    except Exception as exc:  # noqa: BLE001 - translated to a user-facing source error
        raise CaseMasterError(f"OpenAPIを読み込めません: {openapi_path}: {exc}") from exc

    operations: dict[str, dict[str, str]] = {}
    for path, path_item in (api.get("paths") or {}).items():
        for method, operation in (path_item or {}).items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            if operation_id in operations:
                raise CaseMasterError(f"OpenAPIのoperationIdが重複しています: {operation_id}")
            operations[operation_id] = {"path": path, "method": method.upper()}
    return operations


def _contract_case(raw: object, source_path: Path, source_hash: str) -> dict:
    if not isinstance(raw, dict):
        raise CaseMasterError("Layer 1のケースがオブジェクトではありません")
    case_id = raw.get("id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise CaseMasterError("Layer 1のケースに試験IDがありません")
    operation_id = raw.get("operationId")
    if not isinstance(operation_id, str) or not operation_id:
        raise CaseMasterError(f"試験ID {case_id} にoperationIdがありません")

    return {
        "caseId": case_id,
        "kind": "contract",
        "title": str(raw.get("summary") or raw.get("perspective") or case_id),
        "source": {
            "type": "openapi-generated",
            "path": str(source_path),
            "sha256": source_hash,
            "operationId": operation_id,
        },
        "definition": {
            "request": {
                "method": raw.get("method", ""),
                "path": raw.get("path", ""),
                "location": raw.get("in", ""),
                "name": raw.get("paramName", ""),
                "value": raw.get("inputValue", ""),
            },
            "perspective": raw.get("perspective", ""),
            "keyword": raw.get("keyword", ""),
            "notes": raw.get("notes", ""),
        },
        "expected": {
            "status": raw.get("expectedStatus", ""),
            "body": raw.get("expectedResponseBody", ""),
            "headers": raw.get("expectedResponseHeader", ""),
            "responseTime": raw.get("expectedResponseTime", ""),
            "result": raw.get("expectedResult", ""),
        },
        "reviewStatus": "draft",
    }


def _scenario_definition(scenario) -> dict:
    return scenario.case_definition()


def _scenario_case(
    scenario, source_path: Path, source_hash: str, operations: dict[str, dict[str, str]]
) -> dict:
    operation_id = scenario.request.operation_id
    operation = operations.get(operation_id)
    if operation is None:
        raise CaseMasterError(
            f"DBシナリオ「{scenario.name}」のoperationIdがOpenAPIにありません: {operation_id}"
        )

    definition = _scenario_definition(scenario)
    case_id = scenario.case_id

    definition["request"].update(operation)
    return {
        "caseId": case_id,
        "kind": "db-scenario",
        "title": scenario.name,
        "source": {
            "type": "db-scenario-yaml",
            "path": str(source_path),
            "sha256": source_hash,
            "scenarioId": scenario.scenario_id,
            "operationId": operation_id,
        },
        "definition": definition,
        "expected": {
            "response": (
                {
                    "status": definition["responseCheck"]["expectedStatus"],
                    "body": definition["responseCheck"]["expectedBody"],
                    "contains": definition["responseCheck"].get("expectedContains", []),
                    **({"values": definition["responseCheck"]["expectedValues"]}
                       if definition["responseCheck"].get("expectedValues") else {}),
                }
                if definition["responseCheck"]
                else None
            ),
            "database": definition["dbCheck"],
            "databaseResponse": definition.get("dbResponseCheck"),
        },
        "reviewStatus": "draft",
    }


def build_case_master(
    project_name: str,
    contract_output: dict | None,
    db_scenarios_path: str | Path | None,
    openapi_path: str | Path,
) -> dict:
    """Normalize current Layer 1 JSON and optional Layer 2 YAML to master v1."""
    cases: list[dict] = []
    openapi_source = Path(openapi_path)
    openapi_hash = _file_hash(openapi_source)
    if contract_output is not None:
        raw_cases = contract_output.get("cases") if isinstance(contract_output, dict) else None
        if not isinstance(raw_cases, list):
            raise CaseMasterError("Layer 1のケースJSONにcases配列がありません")
        cases.extend(_contract_case(case, openapi_source, openapi_hash) for case in raw_cases)

    source_files = {"openapi": str(Path(openapi_path))}
    if db_scenarios_path is not None:
        scenario_path = Path(db_scenarios_path)
        scenario_hash = _file_hash(scenario_path)
        try:
            scenarios = _load_scenarios(scenario_path)
            operations = _operation_index(Path(openapi_path))
        except CaseMasterError:
            raise
        except Exception as exc:  # noqa: BLE001 - keep malformed YAML tied to its file
            raise CaseMasterError(f"DBシナリオを読み込めません: {scenario_path}: {exc}") from exc
        cases.extend(_scenario_case(item, scenario_path, scenario_hash, operations) for item in scenarios)
        source_files["dbScenarios"] = str(scenario_path)

    if not cases:
        raise CaseMasterError("試験ケースがありません。OpenAPIケースまたはDBシナリオを用意してください")

    seen: set[str] = set()
    for case in cases:
        case_id = case["caseId"]
        if case_id in seen:
            raise CaseMasterError(f"試験IDが重複しています: {case_id}")
        seen.add(case_id)
        case["definitionHash"] = _definition_hash(case)

    return {
        "format": "api-tester.case-master",
        "schemaVersion": 1,
        "project": {"name": project_name, "sources": source_files},
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cases": cases,
    }


def write_case_master(master: dict, output_path: str | Path) -> None:
    for case in master.get("cases", []):
        case.setdefault("reviewStatus", "draft")
        fingerprint = _definition_hash(case)
        if case.get("definitionHash") not in (None, fingerprint):
            raise CaseMasterError(f"試験ID {case.get('caseId')} の定義ハッシュが一致しません")
        case["definitionHash"] = fingerprint
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_case_master(master_path: str | Path) -> dict:
    path = Path(master_path)
    try:
        master = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseMasterError(f"試験ケースマスターを読み込めません: {exc}") from exc
    if not isinstance(master, dict) or master.get("format") != "api-tester.case-master":
        raise CaseMasterError("対応していない試験ケースマスター形式です")
    if master.get("schemaVersion") != 1 or not isinstance(master.get("cases"), list):
        raise CaseMasterError("試験ケースマスターのバージョンまたはcases配列が不正です")

    seen: set[str] = set()
    for case in master["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
            raise CaseMasterError("試験ケースマスターに不正なケースがあります")
        case_id = case["caseId"]
        if case_id in seen:
            raise CaseMasterError(f"試験IDが重複しています: {case_id}")
        seen.add(case_id)
        status = case.get("reviewStatus", "draft")
        if status not in _REVIEW_STATES:
            raise CaseMasterError(f"試験ID {case_id} のレビュー状態が不正です")
        expected_hash = _definition_hash(case)
        recorded_hash = case.get("definitionHash")
        if recorded_hash is not None and recorded_hash != expected_hash:
            raise CaseMasterError(
                f"試験ID {case_id} の定義が生成後に変更されています。元の入力から再生成してください"
            )
        # 初版（fingerprint 導入前）のマスターは読み取れるが、承認状態を引き継がない。
        if recorded_hash is None:
            case["reviewStatus"] = "draft"
            case["definitionHash"] = expected_hash
    return master


def save_case_master_reviews(master_path: str | Path, updates: dict[str, str]) -> dict:
    if not isinstance(updates, dict) or not updates:
        raise CaseMasterError("保存するレビュー状態がありません")
    master = load_case_master(master_path)
    cases = {case["caseId"]: case for case in master["cases"]}
    for case_id, next_status in updates.items():
        case = cases.get(case_id)
        if case is None:
            raise CaseMasterError(f"試験IDが見つかりません: {case_id}")
        if next_status not in _REVIEW_STATES:
            raise CaseMasterError(f"試験ID {case_id} のレビュー状態が不正です")
        current_status = case.get("reviewStatus", "draft")
        if next_status not in _REVIEW_TRANSITIONS[current_status]:
            raise CaseMasterError(
                f"試験ID {case_id} は {current_status} から {next_status} へ変更できません"
            )
    for case_id, next_status in updates.items():
        cases[case_id]["reviewStatus"] = next_status

    path = Path(master_path)
    spec_path = path.parent / "case-spec.xlsx"
    if spec_path.is_file():
        try:
            from workflow.spec_writer import write_case_spec_excel

            write_case_spec_excel(master, spec_path)
            execution_artifacts = master.setdefault("executionArtifacts", {})
            execution_artifacts["caseSpecExcelSha256"] = hashlib.sha256(
                spec_path.read_bytes()
            ).hexdigest()
        except (OSError, ValueError) as exc:
            raise CaseMasterError(f"レビュー状態を試験仕様Excelへ反映できません: {exc}") from exc

    registry_path = _review_registry_path(path)
    if registry_path.is_file():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CaseMasterError(f"レビュー履歴を読み込めません: {exc}") from exc
        if registry.get("format") != "api-tester.case-reviews" or not isinstance(registry.get("reviews"), dict):
            raise CaseMasterError("レビュー履歴の形式が不正です")
    else:
        registry = {"format": "api-tester.case-reviews", "schemaVersion": 1, "reviews": {}}
    registry["reviews"].update({case["definitionHash"]: case["reviewStatus"] for case in cases.values()})
    _atomic_write_json(registry_path, registry)
    _atomic_write_json(path, master)
    return master


def apply_case_review_registry(master: dict, registry_path: str | Path) -> dict:
    path = Path(registry_path)
    if not path.is_file():
        return master
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseMasterError(f"レビュー履歴を読み込めません: {exc}") from exc
    if (
        not isinstance(registry, dict)
        or registry.get("format") != "api-tester.case-reviews"
        or registry.get("schemaVersion") != 1
        or not isinstance(registry.get("reviews"), dict)
    ):
        raise CaseMasterError("レビュー履歴の形式が不正です")
    for case in master.get("cases", []):
        status = registry["reviews"].get(case.get("definitionHash"))
        if status in _REVIEW_STATES:
            case["reviewStatus"] = status
    return master
