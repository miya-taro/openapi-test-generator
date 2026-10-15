from __future__ import annotations

import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from workflow.models import (
    ArtifactPaths,
    ProjectConfig,
    ProjectConfigError,
    RunRequest,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _new_run_id() -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def artifact_paths(config: ProjectConfig, run_id: str | None = None) -> ArtifactPaths:
    resolved_run_id = run_id or _new_run_id()
    if not _SAFE_RUN_ID.fullmatch(resolved_run_id):
        raise ProjectConfigError("run_id に使用できない文字が含まれています")
    run_dir = config.output_dir / resolved_run_id
    return ArtifactPaths(
        run_id=resolved_run_id,
        run_dir=run_dir,
        cases_json=run_dir / "test-cases.json",
        case_master_json=run_dir / "case-master.json",
        case_spec_excel=run_dir / "case-spec.xlsx",
        spec_excel=run_dir / "test-spec.xlsx",
        result_excel=run_dir / "test-result.xlsx",
        junit_xml=run_dir / "contract-junit.xml",
        db_report_excel=run_dir / "db-scenario-result.xlsx",
        db_junit_xml=run_dir / "db-scenario-junit.xml",
        db_evidence_json=run_dir / "db-scenario-evidence.json",
        html_report=run_dir / "report.html",
        failed_case_ids_json=run_dir / "failed-case-ids.json",
    )


def build_generate_command(
    config: ProjectConfig, paths: ArtifactPaths, request: RunRequest | None = None
) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "src" / "cli.py"),
        str(config.openapi_path),
        "--output",
        str(paths.cases_json),
        "--excel-output",
        str(paths.spec_excel),
        "--base-url",
        config.base_url,
    ]
    if config.selected_operations:
        command.extend(["--operations", ",".join(config.selected_operations)])
    if request is not None:
        if not request.include_normal:
            command.append("--no-normal")
        if not request.include_abnormal:
            command.append("--no-abnormal")
    return command


def build_contract_run_command(
    config: ProjectConfig, request: RunRequest, paths: ArtifactPaths,
    case_ids: tuple[str, ...] = (),
) -> list[str]:
    if request.parallel < 1:
        raise ProjectConfigError("parallel は1以上で指定してください")
    if request.persist_cookies and request.parallel > 1:
        raise ProjectConfigError("Cookie維持と並列実行は同時に使用できません")

    command = [
        sys.executable,
        str(REPO_ROOT / "runner" / "pytest_runner.py"),
        str(paths.case_master_json),
        "--kind", "contract",
        "--spec-output", str(paths.spec_excel),
        "--base-url",
        config.base_url,
        "--output",
        str(paths.result_excel),
        "--junit-xml",
        str(paths.junit_xml),
        "--parallel",
        str(request.parallel),
    ]
    optional_paths = (
        ("--setup", config.setup_sql_path),
        ("--teardown", config.teardown_sql_path),
        ("--config", request.runtime_config_path),
        ("--auth-config", request.auth_config_path),
    )
    for flag, value in optional_paths:
        if value is not None:
            command.extend([flag, str(value)])
    if request.fail_fast:
        command.append("--fail-fast")
    if request.dry_run:
        command.append("--dry-run")
    if request.full_body:
        command.append("--full-body")
    if request.skip_health_check:
        command.append("--skip-health-check")
    if request.persist_cookies:
        command.append("--cookie-jar")
    if case_ids:
        command.extend(["--case-ids", ",".join(case_ids)])
    return command


def build_db_scenario_command(
    config: ProjectConfig, request: RunRequest, paths: ArtifactPaths,
    case_ids: tuple[str, ...] = (),
) -> list[str]:
    if config.db_scenarios_path is None:
        raise ProjectConfigError("DBシナリオファイルが指定されていません")

    command = [
        sys.executable,
        str(REPO_ROOT / "runner" / "pytest_runner.py"),
        str(paths.case_master_json),
        "--kind", "db-scenario",
        "--base-url",
        config.base_url,
        "--report-output",
        str(paths.db_report_excel),
        "--junit-xml",
        str(paths.db_junit_xml),
        "--evidence-output",
        str(paths.db_evidence_json),
        "--skip-health-check",
    ]
    if request.runtime_config_path is not None:
        command.extend(["--config", str(request.runtime_config_path)])
    if request.auth_config_path is not None:
        command.extend(["--auth-config", str(request.auth_config_path)])
    if request.persist_cookies:
        command.append("--cookie-jar")
    if request.dry_run:
        command.append("--dry-run")
    if case_ids:
        command.extend(["--case-ids", ",".join(case_ids)])
    return command
