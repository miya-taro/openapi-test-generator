from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class ProjectConfigError(ValueError):
    """プロジェクト設定が安全に読み込めない場合のエラー。"""


@dataclass(frozen=True)
class ProjectConfig:
    schema_version: int
    name: str
    project_dir: Path
    openapi_path: Path
    base_url: str
    output_dir: Path
    selected_operations: tuple[str, ...] = ()
    setup_sql_path: Path | None = None
    teardown_sql_path: Path | None = None
    db_scenarios_path: Path | None = None


@dataclass(frozen=True)
class RunRequest:
    workflow: Literal["contract", "db-scenarios"]
    project_file: Path
    runtime_config_path: Path | None = None
    auth_config_path: Path | None = None
    parallel: int = 1
    fail_fast: bool = False
    persist_cookies: bool = False
    dry_run: bool = False
    full_body: bool = False
    skip_health_check: bool = True
    include_normal: bool = True
    include_abnormal: bool = True


@dataclass(frozen=True)
class ArtifactPaths:
    run_id: str
    run_dir: Path
    cases_json: Path
    case_master_json: Path
    case_spec_excel: Path
    spec_excel: Path
    result_excel: Path
    junit_xml: Path
    db_report_excel: Path
    db_junit_xml: Path
    db_evidence_json: Path
    html_report: Path
    failed_case_ids_json: Path
