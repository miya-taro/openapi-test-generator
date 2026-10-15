from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from runner.auth_login import AuthLoginError, build_auth_header, load_auth_config, perform_login

from workflow.commands import (
    artifact_paths,
    build_contract_run_command,
    build_db_scenario_command,
    build_generate_command,
)
from workflow.events import WorkflowEvent, emit_event
from workflow.executor import StageResult, run_command
from workflow.case_master import (
    CaseMasterError,
    apply_case_review_registry,
    build_case_master,
    load_case_master,
    write_case_master,
)
from workflow.spec_writer import write_case_spec_excel
from workflow.html_report import write_failed_case_ids, write_html_report
from workflow.models import ProjectConfigError, RunRequest
from workflow.project_store import load_project
from workflow.schemathesis_report import write_exploratory_html
from workflow.schemathesis_runner import build_schemathesis_command


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="API試験の統一ワークフロー")
    sub = parser.add_subparsers(dest="workflow", required=True)
    for name in ("run-contract", "run-db-scenarios"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
        command.add_argument("--runtime-config")
        command.add_argument("--auth-config")
        command.add_argument("--cookie-jar", action="store_true")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--case-ids", help="カンマ区切りの試験IDで実行対象を限定")
    contract = sub.choices["run-contract"]
    contract.add_argument("--parallel", type=int, default=1)
    contract.add_argument("--fail-fast", action="store_true")
    contract.add_argument("--full-body", action="store_true")
    contract.add_argument("--no-normal", action="store_true")
    contract.add_argument("--no-abnormal", action="store_true")

    prepare = sub.add_parser("prepare-contract")
    prepare.add_argument("--project", required=True)
    prepare.add_argument("--no-normal", action="store_true")
    prepare.add_argument("--no-abnormal", action="store_true")

    execute = sub.add_parser("execute-contract")
    execute.add_argument("--project", required=True)
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--runtime-config")
    execute.add_argument("--auth-config")
    execute.add_argument("--cookie-jar", action="store_true")
    execute.add_argument("--dry-run", action="store_true")
    execute.add_argument("--case-ids", help="カンマ区切りの試験IDで実行対象を限定")
    execute.add_argument("--parallel", type=int, default=1)
    execute.add_argument("--fail-fast", action="store_true")
    execute.add_argument("--full-body", action="store_true")
    execute.add_argument("--allow-draft", action="store_true", help="未承認ケースを予備実行する")

    prepare_db = sub.add_parser("prepare-db-scenarios")
    prepare_db.add_argument("--project", required=True)

    explore = sub.add_parser("run-schemathesis")
    explore.add_argument("--project", required=True)
    explore.add_argument("--include-mutating", action="store_true")
    explore.add_argument("--max-examples", type=int, default=10)
    explore.add_argument("--auth-config")
    explore.add_argument("--save-cassette", action="store_true")

    execute_db = sub.add_parser("execute-db-scenarios")
    execute_db.add_argument("--project", required=True)
    execute_db.add_argument("--run-id", required=True)
    execute_db.add_argument("--runtime-config")
    execute_db.add_argument("--auth-config")
    execute_db.add_argument("--cookie-jar", action="store_true")
    execute_db.add_argument("--dry-run", action="store_true")
    execute_db.add_argument("--case-ids", help="カンマ区切りの試験IDで実行対象を限定")
    execute_db.add_argument("--allow-draft", action="store_true", help="未承認ケースを予備実行する")
    return parser


def _artifact(emit, kind: str, path: Path) -> None:
    emit(WorkflowEvent(type="artifact", kind=kind, path=str(path)))
    if kind in {"result_excel", "db_report_excel"} and path.with_suffix(".json").is_file():
        emit(WorkflowEvent(type="artifact", kind="execution_result_json", path=str(path.with_suffix(".json"))))


def _write_contract_case_master(config, paths) -> None:
    try:
        contract_output = json.loads(paths.cases_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseMasterError(f"生成されたテストケースJSONを読めません: {exc}") from exc
    master = build_case_master(
        config.name, contract_output, config.db_scenarios_path, config.openapi_path
    )
    apply_case_review_registry(master, config.output_dir / "case-reviews.json")
    write_case_master(master, paths.case_master_json)
    write_case_spec_excel(master, paths.case_spec_excel)


def _write_db_case_master(config, paths) -> None:
    master = build_case_master(
        config.name, None, config.db_scenarios_path, config.openapi_path
    )
    apply_case_review_registry(master, config.output_dir / "case-reviews.json")
    write_case_spec_excel(master, paths.case_spec_excel)
    write_case_master(master, paths.case_master_json)


def _write_html_report(paths, junit_paths: list[Path], artifacts: dict[str, Path]) -> None:
    for label, path in list(artifacts.items()):
        if path in (paths.result_excel, paths.db_report_excel) and path.with_suffix(".json").is_file():
            artifacts[label.replace("Excel", "JSON")] = path.with_suffix(".json")
    write_html_report(paths.case_master_json, junit_paths, paths.html_report, artifacts)


def _emit_contract_result(emit, paths, result: StageResult) -> int:
    _artifact(emit, "spec_excel", paths.spec_excel)
    _artifact(emit, "result_excel", paths.result_excel)
    _artifact(emit, "junit_xml", paths.junit_xml)
    db_evidence = paths.result_excel.with_name(paths.result_excel.stem + "-db-evidence.json")
    if db_evidence.is_file():
        _artifact(emit, "contract_db_evidence_json", db_evidence)
    try:
        write_failed_case_ids([paths.junit_xml], paths.failed_case_ids_json)
        _artifact(emit, "failed_case_ids_json", paths.failed_case_ids_json)
        _write_html_report(
            paths, [paths.junit_xml],
            {"試験仕様書": paths.case_spec_excel, "結果Excel": paths.result_excel,
             "JUnit XML": paths.junit_xml,
             **({"異常系DB変更なし証跡": db_evidence} if db_evidence.is_file() else {})},
        )
        _artifact(emit, "html_report", paths.html_report)
    except (CaseMasterError, OSError, ValueError) as exc:
        emit(WorkflowEvent.log("report", f"HTML結果レポートを作成できませんでした: {exc}", level="error"))
        return _finish(emit, StageResult.failed(3))
    return _finish(emit, result)


def _validate_prepared_cases(config, paths) -> dict:
    """Rebuild from current inputs; never execute a stale or altered reviewed case set."""
    if not paths.run_dir.is_dir():
        raise CaseMasterError("準備済み試験がありません。先に試験ケースを作成してください")
    for required in (paths.cases_json, paths.case_master_json):
        if not required.is_file():
            raise CaseMasterError(f"準備済み成果物がありません: {required.name}")
    try:
        contract_output = json.loads(paths.cases_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseMasterError(f"準備済み試験ケースを読めません: {exc}") from exc

    current = build_case_master(
        config.name, contract_output, config.db_scenarios_path, config.openapi_path
    )
    saved = load_case_master(paths.case_master_json)
    current_cases = {case["caseId"]: case for case in current["cases"]}
    saved_cases = {case["caseId"]: case for case in saved["cases"]}
    if set(current_cases) != set(saved_cases) or any(
        current_cases[case_id]["definitionHash"] != saved_cases[case_id].get("definitionHash")
        for case_id in current_cases
    ):
        raise CaseMasterError("試験定義または入力ファイルが準備後に変更されています。再度ケースを作成してください")

    apply_case_review_registry(current, config.output_dir / "case-reviews.json")
    write_case_master(current, paths.case_master_json)
    write_case_spec_excel(current, paths.case_spec_excel)
    return current


def _validate_prepared_db_cases(config, paths) -> dict:
    if not paths.run_dir.is_dir() or not paths.case_master_json.is_file():
        raise CaseMasterError("準備済みDBシナリオがありません。先にシナリオケースを作成してください")
    current = build_case_master(config.name, None, config.db_scenarios_path, config.openapi_path)
    saved = load_case_master(paths.case_master_json)
    current_cases = {case["caseId"]: case for case in current["cases"]}
    saved_cases = {case["caseId"]: case for case in saved["cases"]}
    if set(current_cases) != set(saved_cases) or any(
        current_cases[case_id]["definitionHash"] != saved_cases[case_id].get("definitionHash")
        for case_id in current_cases
    ):
        raise CaseMasterError("DBシナリオまたは入力ファイルが準備後に変更されています。再度ケースを作成してください")
    apply_case_review_registry(current, config.output_dir / "case-reviews.json")
    write_case_master(current, paths.case_master_json)
    write_case_spec_excel(current, paths.case_spec_excel)
    return current


def _emit_db_result(emit, paths, result: StageResult) -> int:
    _artifact(emit, "db_report_excel", paths.db_report_excel)
    _artifact(emit, "db_junit_xml", paths.db_junit_xml)
    _artifact(emit, "db_evidence_json", paths.db_evidence_json)
    try:
        write_failed_case_ids([paths.db_junit_xml], paths.failed_case_ids_json)
        _artifact(emit, "failed_case_ids_json", paths.failed_case_ids_json)
        _write_html_report(
            paths, [paths.db_junit_xml],
            {"試験仕様書": paths.case_spec_excel, "DB結果Excel": paths.db_report_excel,
             "DB JUnit XML": paths.db_junit_xml, "DB比較エビデンス": paths.db_evidence_json},
        )
        _artifact(emit, "html_report", paths.html_report)
    except (CaseMasterError, OSError, ValueError) as exc:
        emit(WorkflowEvent.log("report", f"HTML結果レポートを作成できませんでした: {exc}", level="error"))
        return _finish(emit, StageResult.failed(3))
    return _finish(emit, result)


def _finish(emit, result: StageResult) -> int:
    emit(WorkflowEvent.workflow_finished(result.status, result.exit_code))
    return 3 if result.exit_code < 0 else result.exit_code


_SCHEMATHESIS_HEADER_ENV = "API_TESTER_SCHEMATHESIS_HEADER"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _write_schemathesis_config(
    path: Path, header_name: str | None = None, *, include_mutating: bool = False,
) -> None:
    lines = ["color = false", "seed = 1", "cache.enabled = false"]
    if header_name:
        lines.extend([
            "",
            f"headers = {{ {_toml_string(header_name)} = \"${{{_SCHEMATHESIS_HEADER_ENV}}}\" }}",
        ])
    if not include_mutating:
        lines.extend(["", "[phases.coverage]", "unexpected-methods = []"])
    lines.extend([
        "",
        "[checks.ignored_auth]",
        "enabled = true",
        "",
        "[output.sanitization]",
        "enabled = true",
        'keys-to-sanitize = ["password", "token", "secret", "authorization", "cookie"]',
        'sensitive-markers = ["token", "key", "secret", "password", "auth", "session", "passwd", "credential"]',
        'replacement = "[REDACTED]"',
        "",
        "[output.truncation]",
        "enabled = true",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _redact_artifact(path: Path, secret_values: tuple[str, ...]) -> None:
    if not secret_values or not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return
    for secret in secret_values:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    path.write_text(text, encoding="utf-8")


def _run_schemathesis(args, config, emit) -> int:
    if not config.openapi_path.is_file():
        emit(WorkflowEvent.log("prepare", f"OpenAPIファイルが見つかりません: {config.openapi_path}", level="error"))
        return _finish(emit, StageResult.failed(3))
    parsed_url = urlparse(config.base_url)
    if parsed_url.username is not None or parsed_url.password is not None:
        emit(WorkflowEvent.log("prepare", "Base URLにユーザー名やパスワードを含めないでください", level="error"))
        return _finish(emit, StageResult.failed(3))
    if not config.selected_operations:
        emit(WorkflowEvent.log("prepare", "対象APIが選択されていません。GUIで試験対象APIを選択してください", level="error"))
        return _finish(emit, StageResult.failed(3))
    if not 1 <= args.max_examples <= 100:
        emit(WorkflowEvent.log("prepare", "探索件数は1..100の範囲で指定してください", level="error"))
        return _finish(emit, StageResult.failed(3))

    executable = shutil.which("schemathesis")
    if executable is None:
        emit(WorkflowEvent.log(
            "prepare",
            "Schemathesisが見つかりません。Python環境で docs/requirements-schemathesis.txt をインストールしてください",
            level="error",
        ))
        return _finish(emit, StageResult.failed(3))

    token = ""
    header_name: str | None = None
    header_value = ""
    if args.auth_config:
        try:
            auth_config = load_auth_config(args.auth_config)
            token = perform_login(config.base_url, auth_config)
            header_name, header_value = build_auth_header(token, auth_config)
            if not token or not header_name or header_name.lower() in {
                "host", "content-length", "transfer-encoding",
            }:
                raise ValueError("invalid auth header")
            requests.Request("GET", config.base_url, headers={header_name: header_value}).prepare()
        except (AuthLoginError, OSError, ValueError, requests.RequestException, TypeError, KeyError, AttributeError):
            emit(WorkflowEvent.log(
                "auth",
                "ログイン認証を完了できませんでした。認証設定と対象APIを確認してください。応答本文などの詳細は記録していません",
                level="error",
            ))
            return _finish(emit, StageResult.failed(3))

    try:
        paths = artifact_paths(config)
        paths.run_dir.mkdir(parents=True, exist_ok=False)
        junit_path = paths.run_dir / "schemathesis-junit.xml"
        html_path = paths.run_dir / "schemathesis-report.html"
        cassette_path = paths.run_dir / "schemathesis-vcr.yaml" if args.save_cassette else None
        config_path = paths.run_dir / "schemathesis.toml"
        manifest_path = paths.run_dir / "schemathesis-manifest.json"
        _write_schemathesis_config(
            config_path, header_name, include_mutating=args.include_mutating,
        )
        manifest = {
            "format": "api-tester.schemathesis-run",
            "schemaVersion": 1,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "selectedOperations": list(config.selected_operations),
            "methods": None if args.include_mutating else ["GET"],
            "includeMutating": bool(args.include_mutating),
            "maxExamplesPerOperation": args.max_examples,
            "seed": 1,
            "workers": 1,
            "authConfigured": bool(args.auth_config),
            "cassetteEnabled": bool(args.save_cassette),
            "status": "running",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = build_schemathesis_command(
            executable,
            config.openapi_path,
            config.base_url,
            junit_path,
            cassette_path,
            include_mutating=args.include_mutating,
            max_examples=args.max_examples,
            selected_operations=config.selected_operations,
            config_path=config_path,
        )
    except (OSError, ValueError) as exc:
        emit(WorkflowEvent.log("prepare", f"探索試験の準備に失敗しました: {exc}", level="error"))
        return _finish(emit, StageResult.failed(3))

    child_env = os.environ.copy()
    child_env["PYTHONUTF8"] = "1"
    child_env["PYTHONIOENCODING"] = "utf-8"
    secret_values = tuple(dict.fromkeys(value for value in (token, header_value) if value))
    if header_value:
        child_env[_SCHEMATHESIS_HEADER_ENV] = header_value
    result = run_command(
        "schemathesis",
        command,
        emit,
        env=child_env,
        warning_exit_codes=(),
        redact_values=secret_values,
    )
    _redact_artifact(junit_path, secret_values)
    if cassette_path is not None:
        _redact_artifact(cassette_path, secret_values)

    manifest["status"] = result.status
    manifest["exitCode"] = result.exit_code
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _artifact(emit, "schemathesis_manifest", manifest_path)
    _artifact(emit, "schemathesis_config", config_path)
    if junit_path.is_file():
        _artifact(emit, "schemathesis_junit", junit_path)
        try:
            write_exploratory_html(junit_path, html_path, title="探索的API試験結果")
        except (OSError, ValueError) as exc:
            emit(WorkflowEvent.log("report", f"探索試験HTMLレポートを作成できませんでした: {exc}", level="error"))
            return _finish(emit, StageResult.failed(3))
        _artifact(emit, "schemathesis_html", html_path)
    elif result.exit_code in {0, 1}:
        emit(WorkflowEvent.log("report", "SchemathesisのJUnit結果が作成されませんでした", level="error"))
        return _finish(emit, StageResult.failed(3))
    if cassette_path is not None and cassette_path.is_file():
        _artifact(emit, "schemathesis_vcr", cassette_path)

    if result.exit_code not in {0, 1}:
        emit(WorkflowEvent.log("schemathesis", "探索試験を実行できませんでした。設定とログを確認してください", level="error"))
        return _finish(emit, StageResult.failed(3))
    if cassette_path is not None:
        emit(WorkflowEvent.log(
            "schemathesis",
            "VCR証跡を保存しました。応答本文などの機密情報が含まれる可能性があります",
            level="warning",
        ))
    return _finish(emit, result)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    emit = lambda event: emit_event(event, sys.stdout)
    try:
        config = load_project(Path(args.project))

        if args.workflow == "prepare-contract":
            paths = artifact_paths(config)
            paths.run_dir.mkdir(parents=True, exist_ok=False)
            request = RunRequest(
                workflow="contract",
                project_file=Path(args.project),
                include_normal=not args.no_normal,
                include_abnormal=not args.no_abnormal,
            )
            generated = run_command("generate", build_generate_command(config, paths, request), emit)
            if generated.exit_code != 0:
                return _finish(emit, generated)
            try:
                _write_contract_case_master(config, paths)
                prepared_master = load_case_master(paths.case_master_json)
            except (CaseMasterError, OSError) as exc:
                emit(WorkflowEvent.log("case-master", f"試験ケースマスターを作成できませんでした: {exc}", level="error"))
                return _finish(emit, StageResult.failed(3))
            for kind, path in (
                ("test_cases_json", paths.cases_json),
                ("spec_excel", paths.spec_excel),
                ("case_master_json", paths.case_master_json),
                ("case_spec_excel", paths.case_spec_excel),
            ):
                _artifact(emit, kind, path)
            if not any(case["kind"] == "contract" for case in prepared_master["cases"]):
                emit(WorkflowEvent.log("prepare", "実行可能なケースがありません。対応状況の未生成・未対応を確認してください", level="error"))
                return _finish(emit, StageResult.failed(3))
            emit(WorkflowEvent.log("prepare", "試験ケースを準備しました。レビュー後に承認済み実行または予備実行を選んでください"))
            return _finish(emit, StageResult.passed())

        if args.workflow == "prepare-db-scenarios":
            paths = artifact_paths(config)
            paths.run_dir.mkdir(parents=True, exist_ok=False)
            try:
                _write_db_case_master(config, paths)
            except (CaseMasterError, OSError) as exc:
                emit(WorkflowEvent.log("case-master", f"DBシナリオケースを作成できませんでした: {exc}", level="error"))
                return _finish(emit, StageResult.failed(3))
            _artifact(emit, "case_master_json", paths.case_master_json)
            _artifact(emit, "case_spec_excel", paths.case_spec_excel)
            emit(WorkflowEvent.log("prepare", "DBシナリオケースを準備しました。内容をレビューしてから実行してください"))
            return _finish(emit, StageResult.passed())

        if args.workflow == "run-schemathesis":
            return _run_schemathesis(args, config, emit)

        if args.workflow == "execute-contract":
            paths = artifact_paths(config, run_id=args.run_id)
            try:
                master = _validate_prepared_cases(config, paths)
                requested_ids = tuple(item.strip() for item in args.case_ids.split(",") if item.strip()) if args.case_ids else ()
                case_by_id = {case["caseId"]: case for case in master["cases"]}
                selected_ids = requested_ids or tuple(
                    case["caseId"] for case in master["cases"] if case["kind"] == "contract"
                )
                if not selected_ids:
                    raise CaseMasterError("実行できるLayer 1ケースがありません")
                unknown = sorted(set(selected_ids) - set(case_by_id))
                if unknown:
                    raise CaseMasterError("試験IDが見つかりません: " + ", ".join(unknown))
                non_contract = [case_id for case_id in selected_ids if case_by_id[case_id]["kind"] != "contract"]
                if non_contract:
                    raise CaseMasterError("Layer 1実行にDBシナリオIDは指定できません: " + ", ".join(non_contract))
                unapproved = [case_id for case_id in selected_ids if case_by_id[case_id]["reviewStatus"] != "approved"]
                if unapproved and not args.allow_draft:
                    raise CaseMasterError(
                        "未承認の試験ケースは実行できません。予備実行する場合は --allow-draft を指定してください: "
                        + ", ".join(unapproved)
                    )
                request = RunRequest(
                    workflow="contract",
                    project_file=Path(args.project),
                    runtime_config_path=Path(args.runtime_config) if args.runtime_config else None,
                    auth_config_path=Path(args.auth_config) if args.auth_config else None,
                    parallel=args.parallel,
                    fail_fast=args.fail_fast,
                    persist_cookies=args.cookie_jar,
                    dry_run=args.dry_run,
                    full_body=args.full_body,
                )
                command = build_contract_run_command(config, request, paths, case_ids=requested_ids)
            except (CaseMasterError, ProjectConfigError) as exc:
                emit(WorkflowEvent.log("prepare", str(exc), level="error"))
                return _finish(emit, StageResult.failed(3))
            result = run_command("execute", command, emit)
            return _emit_contract_result(emit, paths, result)

        if args.workflow == "execute-db-scenarios":
            paths = artifact_paths(config, run_id=args.run_id)
            try:
                master = _validate_prepared_db_cases(config, paths)
                requested_ids = tuple(item.strip() for item in args.case_ids.split(",") if item.strip()) if args.case_ids else ()
                case_by_id = {case["caseId"]: case for case in master["cases"]}
                selected_ids = requested_ids or tuple(case_by_id)
                unknown = sorted(set(selected_ids) - set(case_by_id))
                if unknown:
                    raise CaseMasterError("試験IDが見つかりません: " + ", ".join(unknown))
                unapproved = [case_id for case_id in selected_ids if case_by_id[case_id]["reviewStatus"] != "approved"]
                if unapproved and not args.allow_draft:
                    raise CaseMasterError(
                        "未承認のDBシナリオは実行できません。予備実行する場合は --allow-draft を指定してください: "
                        + ", ".join(unapproved)
                    )
                request = RunRequest(
                    workflow="db-scenarios",
                    project_file=Path(args.project),
                    runtime_config_path=Path(args.runtime_config) if args.runtime_config else None,
                    auth_config_path=Path(args.auth_config) if args.auth_config else None,
                    persist_cookies=args.cookie_jar,
                    dry_run=args.dry_run,
                )
                command = build_db_scenario_command(config, request, paths, case_ids=requested_ids)
            except (CaseMasterError, ProjectConfigError) as exc:
                emit(WorkflowEvent.log("prepare", str(exc), level="error"))
                return _finish(emit, StageResult.failed(3))
            result = run_command("db-scenarios", command, emit)
            return _emit_db_result(emit, paths, result)

        paths = artifact_paths(config)
        paths.run_dir.mkdir(parents=True, exist_ok=False)
        request = RunRequest(
            workflow="contract" if args.workflow == "run-contract" else "db-scenarios",
            project_file=Path(args.project),
            runtime_config_path=Path(args.runtime_config) if args.runtime_config else None,
            auth_config_path=Path(args.auth_config) if args.auth_config else None,
            parallel=getattr(args, "parallel", 1),
            fail_fast=getattr(args, "fail_fast", False),
            persist_cookies=args.cookie_jar,
            dry_run=getattr(args, "dry_run", False),
            full_body=getattr(args, "full_body", False),
            include_normal=not getattr(args, "no_normal", False),
            include_abnormal=not getattr(args, "no_abnormal", False),
        )
        if args.workflow == "run-contract":
            generated = run_command("generate", build_generate_command(config, paths, request), emit)
            if generated.exit_code != 0:
                return _finish(emit, generated)
            try:
                _write_contract_case_master(config, paths)
            except (CaseMasterError, OSError) as exc:
                emit(WorkflowEvent.log("case-master", f"試験ケースマスターを作成できませんでした: {exc}", level="error"))
                return _finish(emit, StageResult.failed(3))
            _artifact(emit, "case_master_json", paths.case_master_json)
            _artifact(emit, "case_spec_excel", paths.case_spec_excel)
            result = run_command(
                "execute", build_contract_run_command(
                    config, request, paths,
                    case_ids=tuple(args.case_ids.split(",")) if args.case_ids else (),
                ), emit
            )
            _artifact(emit, "test_cases_json", paths.cases_json)
            _artifact(emit, "spec_excel", paths.spec_excel)
            _artifact(emit, "result_excel", paths.result_excel)
            _artifact(emit, "junit_xml", paths.junit_xml)
            try:
                write_failed_case_ids([paths.junit_xml], paths.failed_case_ids_json)
                _artifact(emit, "failed_case_ids_json", paths.failed_case_ids_json)
                _write_html_report(
                    paths, [paths.junit_xml],
                    {"試験仕様書": paths.case_spec_excel, "結果Excel": paths.result_excel,
                     "JUnit XML": paths.junit_xml},
                )
                _artifact(emit, "html_report", paths.html_report)
            except (CaseMasterError, OSError, ValueError) as exc:
                emit(WorkflowEvent.log("report", f"HTML結果レポートを作成できませんでした: {exc}", level="error"))
                return _finish(emit, StageResult.failed(3))
            return _finish(emit, result)

        command = build_db_scenario_command(
            config, request, paths,
            case_ids=tuple(args.case_ids.split(",")) if args.case_ids else (),
        )
        try:
            _write_db_case_master(config, paths)
        except (CaseMasterError, OSError) as exc:
            emit(WorkflowEvent.log("case-master", f"試験ケースマスターを作成できませんでした: {exc}", level="error"))
            return _finish(emit, StageResult.failed(3))
        _artifact(emit, "case_master_json", paths.case_master_json)
        _artifact(emit, "case_spec_excel", paths.case_spec_excel)
        result = run_command("db-scenarios", command, emit)
        _artifact(emit, "db_report_excel", paths.db_report_excel)
        _artifact(emit, "db_junit_xml", paths.db_junit_xml)
        _artifact(emit, "db_evidence_json", paths.db_evidence_json)
        try:
            write_failed_case_ids([paths.db_junit_xml], paths.failed_case_ids_json)
            _artifact(emit, "failed_case_ids_json", paths.failed_case_ids_json)
            _write_html_report(
                paths, [paths.db_junit_xml],
                {"試験仕様書": paths.case_spec_excel, "DB結果Excel": paths.db_report_excel,
                 "DB JUnit XML": paths.db_junit_xml, "DB比較エビデンス": paths.db_evidence_json},
            )
            _artifact(emit, "html_report", paths.html_report)
        except (CaseMasterError, OSError, ValueError) as exc:
            emit(WorkflowEvent.log("report", f"HTML結果レポートを作成できませんでした: {exc}", level="error"))
            return _finish(emit, StageResult.failed(3))
        return _finish(emit, result)
    except (OSError, ProjectConfigError, CaseMasterError) as exc:
        emit(WorkflowEvent.log("prepare", str(exc), level="error"))
        return _finish(emit, StageResult(status="error", exit_code=3))


if __name__ == "__main__":
    raise SystemExit(main())
