import sys

import pytest

from workflow.commands import (
    REPO_ROOT,
    artifact_paths,
    build_contract_run_command,
    build_db_scenario_command,
    build_generate_command,
)
from workflow.models import ProjectConfig, ProjectConfigError, RunRequest


@pytest.fixture
def project_config(tmp_path):
    return ProjectConfig(
        schema_version=1,
        name="orders",
        project_dir=tmp_path,
        openapi_path=tmp_path / "openapi.json",
        base_url="http://vm.local/api",
        output_dir=tmp_path / "artifacts",
        selected_operations=("getOrder", "createOrder"),
        setup_sql_path=tmp_path / "setup.sql",
        teardown_sql_path=tmp_path / "teardown.sql",
        db_scenarios_path=tmp_path / "scenarios.yaml",
    )


@pytest.fixture
def run_request(tmp_path):
    return RunRequest(
        workflow="contract",
        project_file=tmp_path / "project.json",
        runtime_config_path=tmp_path / "runtime-db.json",
        auth_config_path=tmp_path / "runtime-auth.json",
        parallel=4,
        fail_fast=True,
    )


def test_contract_commands_use_stable_artifact_paths(project_config, run_request):
    paths = artifact_paths(project_config, run_id="20260922-120000-deadbeef")
    generate = build_generate_command(project_config, paths)
    execute = build_contract_run_command(project_config, run_request, paths)

    assert paths.run_dir.name == "20260922-120000-deadbeef"
    assert paths.spec_excel.name == "test-spec.xlsx"
    assert paths.cases_json.name == "test-cases.json"
    assert paths.case_master_json.name == "case-master.json"
    assert paths.case_spec_excel.name == "case-spec.xlsx"
    assert paths.html_report.name == "report.html"
    assert paths.result_excel.name == "test-result.xlsx"
    assert paths.junit_xml.name == "contract-junit.xml"
    assert generate[:2] == [sys.executable, str(REPO_ROOT / "src" / "cli.py")]
    assert generate[2] == str(project_config.openapi_path)
    assert generate[generate.index("--operations") + 1] == "getOrder,createOrder"
    assert execute[:2] == [sys.executable, str(REPO_ROOT / "runner" / "runner.py")]
    assert execute[execute.index("--output") + 1] == str(paths.result_excel)
    assert execute[execute.index("--junit-xml") + 1] == str(paths.junit_xml)


def test_contract_command_includes_runtime_paths_without_secret_values(
    project_config, run_request
):
    command = build_contract_run_command(
        project_config,
        run_request,
        artifact_paths(project_config, run_id="run"),
    )
    joined = " ".join(command).lower()

    assert "password" not in joined
    assert "bearer " not in joined
    assert str(run_request.runtime_config_path) in command
    assert str(run_request.auth_config_path) in command
    assert command[command.index("--parallel") + 1] == "4"
    assert "--fail-fast" in command
    assert str(project_config.setup_sql_path) in command
    assert str(project_config.teardown_sql_path) in command


def test_cookie_persistence_rejects_parallel_contract_execution(
    project_config, run_request
):
    unsafe = RunRequest(
        workflow="contract",
        project_file=run_request.project_file,
        parallel=2,
        persist_cookies=True,
    )

    with pytest.raises(ProjectConfigError, match="Cookie"):
        build_contract_run_command(
            project_config, unsafe, artifact_paths(project_config, run_id="run")
        )


def test_db_scenario_command_requires_scenario_and_runtime_config(project_config, tmp_path):
    request = RunRequest(
        workflow="db-scenarios",
        project_file=tmp_path / "project.json",
        runtime_config_path=None,
    )

    with pytest.raises(ProjectConfigError, match="DB接続"):
        build_db_scenario_command(
            project_config, request, artifact_paths(project_config, run_id="run")
        )


def test_db_scenario_command_uses_report_and_junit_paths(project_config, tmp_path):
    request = RunRequest(
        workflow="db-scenarios",
        project_file=tmp_path / "project.json",
        runtime_config_path=tmp_path / "runtime-db.json",
        auth_config_path=tmp_path / "runtime-auth.json",
        persist_cookies=True,
        dry_run=True,
    )
    paths = artifact_paths(project_config, run_id="run")

    command = build_db_scenario_command(project_config, request, paths)

    assert command[:2] == [
        sys.executable,
        str(REPO_ROOT / "runner" / "db_scenario_runner.py"),
    ]
    assert command[command.index("--report-output") + 1] == str(paths.db_report_excel)
    assert command[command.index("--junit-xml") + 1] == str(paths.db_junit_xml)
    assert "--cookie-jar" in command
    assert "--dry-run" in command
    assert command.count("--dry-run") == 1
    assert "--skip-health-check" in command


def test_artifact_paths_reject_unsafe_run_id(project_config):
    with pytest.raises(ProjectConfigError, match="run_id"):
        artifact_paths(project_config, run_id="../outside")


def test_contract_commands_preserve_existing_advanced_execution_options(project_config, tmp_path):
    request = RunRequest(
        workflow="contract",
        project_file=tmp_path / "project.json",
        dry_run=True,
        full_body=True,
        skip_health_check=True,
        include_normal=False,
        include_abnormal=True,
    )
    paths = artifact_paths(project_config, run_id="run")

    generate = build_generate_command(project_config, paths, request)
    execute = build_contract_run_command(project_config, request, paths)

    assert "--no-normal" in generate
    assert "--no-abnormal" not in generate
    assert "--dry-run" in execute
    assert "--full-body" in execute
    assert "--skip-health-check" in execute


def test_contract_and_db_commands_can_filter_selected_case_ids(project_config, tmp_path):
    contract_request = RunRequest(workflow="contract", project_file=tmp_path / "project.json")
    db_request = RunRequest(
        workflow="db-scenarios", project_file=tmp_path / "project.json",
        runtime_config_path=tmp_path / "db.json",
    )
    paths = artifact_paths(project_config, run_id="run")

    contract = build_contract_run_command(
        project_config, contract_request, paths, case_ids=("TC-1", "TC-2")
    )
    db = build_db_scenario_command(project_config, db_request, paths, case_ids=("DB-1",))

    assert contract[contract.index("--case-ids") + 1] == "TC-1,TC-2"
    assert db[db.index("--case-ids") + 1] == "DB-1"
