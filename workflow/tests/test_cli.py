import json
from pathlib import Path

from workflow import cli
from workflow.case_master import save_case_master_reviews
from workflow.executor import StageResult


def _write_project(tmp_path, *, db_scenarios=False):
    (tmp_path / "openapi.json").write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "fixture", "version": "1"}, "paths": {},
    }), encoding="utf-8")
    path = tmp_path / "project.json"
    project = {
        "schemaVersion": 1,
        "name": "sample",
        "openapiPath": "openapi.json",
        "baseUrl": "http://vm.local/api",
        "outputDir": "artifacts",
    }
    if db_scenarios:
        project["dbScenariosPath"] = "scenarios.yaml"
    path.write_text(json.dumps(project), encoding="utf-8")
    return path


def _write_db_scenario_project(tmp_path):
    project = _write_project(tmp_path, db_scenarios=True)
    (tmp_path / "openapi.json").write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "fixture", "version": "1"},
        "paths": {"/users/{id}": {
            "get": {"operationId": "getUser", "responses": {"200": {"description": "ok"}}}
        }},
    }), encoding="utf-8")
    (tmp_path / "scenarios.yaml").write_text("""
scenarios:
  - id: readUser
    name: Read user
    request:
      operationId: getUser
      path_params: {id: 1}
    response_check:
      expect: {status: 200}
""", encoding="utf-8")
    return project


def test_run_contract_emits_generate_then_execute(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run_command(stage, command, emit):
        calls.append(stage)
        if stage == "generate":
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"cases": [{
                "id": "TC-listUsers-001",
                "operationId": "listUsers",
                "path": "/users",
                "method": "GET",
                "expectedStatus": "200",
            }]}), encoding="utf-8")
            Path(command[command.index("--excel-output") + 1]).touch()
        return StageResult.passed()

    monkeypatch.setattr(cli, "run_command", fake_run_command)

    code = cli.main(["run-contract", "--project", str(_write_project(tmp_path))])

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert calls == ["generate", "execute"]
    assert events[-1] == {
        "type": "workflow_finished", "status": "passed", "exit_code": 0
    }
    assert {event.get("kind") for event in events if event["type"] == "artifact"} == {
        "test_cases_json", "case_master_json", "case_spec_excel", "spec_excel",
        "result_excel", "junit_xml", "failed_case_ids_json", "html_report"
    }
    master_path = next(event["path"] for event in events if event.get("kind") == "case_master_json")
    assert json.loads(Path(master_path).read_text(encoding="utf-8"))["cases"][0]["caseId"] == "TC-listUsers-001"


def test_generation_failure_does_not_execute(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        cli,
        "run_command",
        lambda stage, command, emit: calls.append(stage) or StageResult.failed(1),
    )
    assert cli.main(["run-contract", "--project", str(_write_project(tmp_path))]) == 1
    assert calls == ["generate"]


def test_warning_exit_is_preserved(monkeypatch, tmp_path):
    results = iter([StageResult.passed(), StageResult(status="warning", exit_code=2)])

    def fake_run_command(stage, command, emit):
        if stage == "generate":
            output_path = Path(command[command.index("--output") + 1])
            output_path.write_text(json.dumps({"cases": [{
                "id": "TC-listUsers-001", "operationId": "listUsers", "path": "/users",
                "method": "GET", "expectedStatus": "200",
            }]}), encoding="utf-8")
            Path(command[command.index("--excel-output") + 1]).touch()
        return next(results)

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.main(["run-contract", "--project", str(_write_project(tmp_path))]) == 2


def test_contract_workflow_emits_failed_case_id_list(monkeypatch, tmp_path, capsys):
    def fake_run_command(stage, command, emit):
        if stage == "generate":
            output = Path(command[command.index("--output") + 1])
            output.write_text(json.dumps({"cases": [{
                "id": "TC-listUsers-001", "operationId": "listUsers", "path": "/users",
                "method": "GET", "expectedStatus": "200",
            }]}), encoding="utf-8")
            Path(command[command.index("--excel-output") + 1]).touch()
            return StageResult.passed()
        junit_path = Path(command[command.index("--junit-xml") + 1])
        junit_path.write_text(
            '<testsuites><testsuite><testcase name="TC-listUsers-001"><failure/></testcase></testsuite></testsuites>',
            encoding="utf-8",
        )
        return StageResult.failed(1)

    monkeypatch.setattr(cli, "run_command", fake_run_command)

    assert cli.main(["run-contract", "--project", str(_write_project(tmp_path))]) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    event = next(event for event in events if event.get("kind") == "failed_case_ids_json")
    assert json.loads(Path(event["path"]).read_text(encoding="utf-8")) == ["TC-listUsers-001"]


def test_prepare_contract_creates_reviewable_master_without_running_api(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run_command(stage, command, emit):
        calls.append(stage)
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"cases": [{
            "id": "TC-listUsers-001", "operationId": "listUsers", "path": "/users",
            "method": "GET", "expectedStatus": "200",
        }]}), encoding="utf-8")
        Path(command[command.index("--excel-output") + 1]).touch()
        return StageResult.passed()

    monkeypatch.setattr(cli, "run_command", fake_run_command)

    code = cli.main(["prepare-contract", "--project", str(_write_project(tmp_path))])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    assert calls == ["generate"]
    assert {event.get("kind") for event in events if event["type"] == "artifact"} >= {
        "case_master_json", "case_spec_excel", "test_cases_json"
    }


def _prepare_one_case(monkeypatch, tmp_path, capsys):
    project = _write_project(tmp_path)
    calls = []

    def fake_run_command(stage, command, emit):
        calls.append(stage)
        if stage == "generate":
            Path(command[command.index("--output") + 1]).write_text(json.dumps({"cases": [{
                "id": "TC-listUsers-001", "operationId": "listUsers", "path": "/users",
                "method": "GET", "expectedStatus": "200",
            }]}), encoding="utf-8")
            Path(command[command.index("--excel-output") + 1]).touch()
        elif stage == "execute":
            Path(command[command.index("--junit-xml") + 1]).write_text(
                '<testsuites><testsuite><testcase name="TC-listUsers-001"/></testsuite></testsuites>',
                encoding="utf-8",
            )
        return StageResult.passed()

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.main(["prepare-contract", "--project", str(project)]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    master_event = next(event for event in events if event.get("kind") == "case_master_json")
    return project, Path(master_event["path"]), calls


def test_execute_contract_blocks_unapproved_cases_before_http_execution(monkeypatch, tmp_path, capsys):
    project, master_path, calls = _prepare_one_case(monkeypatch, tmp_path, capsys)

    code = cli.main([
        "execute-contract", "--project", str(project), "--run-id", master_path.parent.name,
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == ["generate"]
    assert any(event.get("level") == "error" and "未承認" in event.get("message", "") for event in events)


def test_execute_contract_runs_only_after_case_approval(monkeypatch, tmp_path, capsys):
    project, master_path, calls = _prepare_one_case(monkeypatch, tmp_path, capsys)
    save_case_master_reviews(master_path, {"TC-listUsers-001": "reviewed"})
    save_case_master_reviews(master_path, {"TC-listUsers-001": "approved"})

    code = cli.main([
        "execute-contract", "--project", str(project), "--run-id", master_path.parent.name,
        "--runtime-config", str(tmp_path / "runtime.json"), "--parallel", "3",
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    assert calls == ["generate", "execute"]
    assert any(event.get("kind") == "html_report" for event in events)


def test_execute_contract_allows_draft_only_with_explicit_flag(monkeypatch, tmp_path, capsys):
    project, master_path, calls = _prepare_one_case(monkeypatch, tmp_path, capsys)

    code = cli.main([
        "execute-contract", "--project", str(project), "--run-id", master_path.parent.name,
        "--allow-draft",
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    assert calls == ["generate", "execute"]
    assert any(event.get("kind") == "html_report" for event in events)


def test_execute_contract_rejects_changed_openapi_after_review(monkeypatch, tmp_path, capsys):
    project, master_path, calls = _prepare_one_case(monkeypatch, tmp_path, capsys)
    save_case_master_reviews(master_path, {"TC-listUsers-001": "reviewed"})
    save_case_master_reviews(master_path, {"TC-listUsers-001": "approved"})
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "changed", "version": "1"}, "paths": {},
    }), encoding="utf-8")

    code = cli.main([
        "execute-contract", "--project", str(project), "--run-id", master_path.parent.name,
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == ["generate"]
    assert any("変更されています" in event.get("message", "") for event in events)


def test_execute_contract_rejects_edited_runner_workbook(monkeypatch, tmp_path, capsys):
    project, master_path, calls = _prepare_one_case(monkeypatch, tmp_path, capsys)
    spec_excel = master_path.parent / "test-spec.xlsx"
    spec_excel.write_bytes(b"edited after review")

    code = cli.main([
        "execute-contract", "--project", str(project), "--run-id", master_path.parent.name,
        "--allow-draft",
    ])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == ["generate"]
    assert any("Excel" in event.get("message", "") for event in events)


def test_prepare_db_scenarios_does_not_connect_to_db_or_call_api(monkeypatch, tmp_path, capsys):
    project = _write_db_scenario_project(tmp_path)
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda *args: calls.append(args[0]))

    code = cli.main(["prepare-db-scenarios", "--project", str(project)])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    assert calls == []
    master_event = next(event for event in events if event.get("kind") == "case_master_json")
    master = json.loads(Path(master_event["path"]).read_text(encoding="utf-8"))
    assert master["cases"][0]["caseId"] == "DB-readUser"
    assert master["cases"][0]["reviewStatus"] == "draft"


def test_execute_db_scenarios_requires_approval_or_explicit_preview(monkeypatch, tmp_path, capsys):
    project = _write_db_scenario_project(tmp_path)
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda stage, command, emit: calls.append(stage) or StageResult.passed())
    assert cli.main(["prepare-db-scenarios", "--project", str(project)]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    master_path = Path(next(event["path"] for event in events if event.get("kind") == "case_master_json"))
    run_id = master_path.parent.name

    blocked = cli.main([
        "execute-db-scenarios", "--project", str(project), "--run-id", run_id,
        "--runtime-config", str(tmp_path / "db.json"),
    ])
    blocked_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert blocked == 3
    assert calls == []
    assert any("未承認" in event.get("message", "") for event in blocked_events)

    preview = cli.main([
        "execute-db-scenarios", "--project", str(project), "--run-id", run_id,
        "--runtime-config", str(tmp_path / "db.json"), "--allow-draft",
    ])
    preview_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert preview == 0
    assert calls == ["db-scenarios"]
    assert any(event.get("kind") == "html_report" for event in preview_events)


def test_execute_db_scenarios_rejects_edited_review_workbook(monkeypatch, tmp_path, capsys):
    project = _write_db_scenario_project(tmp_path)
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda stage, command, emit: calls.append(stage) or StageResult.passed())
    assert cli.main(["prepare-db-scenarios", "--project", str(project)]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    master_path = Path(next(event["path"] for event in events if event.get("kind") == "case_master_json"))
    (master_path.parent / "case-spec.xlsx").write_bytes(b"edited after review")

    code = cli.main([
        "execute-db-scenarios", "--project", str(project), "--run-id", master_path.parent.name,
        "--runtime-config", str(tmp_path / "db.json"), "--allow-draft",
    ])
    result_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == []
    assert any("Excel" in event.get("message", "") for event in result_events)


def test_execute_db_scenarios_uses_same_approved_case_id_in_runner(monkeypatch, tmp_path, capsys):
    project = _write_db_scenario_project(tmp_path)
    calls = []

    def fake_run_command(stage, command, emit):
        calls.append((stage, command))
        Path(command[command.index("--junit-xml") + 1]).write_text(
            '<testsuites><testsuite><testcase name="DB-readUser"/></testsuite></testsuites>',
            encoding="utf-8",
        )
        return StageResult.passed()

    monkeypatch.setattr(cli, "run_command", fake_run_command)
    assert cli.main(["prepare-db-scenarios", "--project", str(project)]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    master_path = Path(next(event["path"] for event in events if event.get("kind") == "case_master_json"))
    save_case_master_reviews(master_path, {"DB-readUser": "reviewed"})
    save_case_master_reviews(master_path, {"DB-readUser": "approved"})

    code = cli.main([
        "execute-db-scenarios", "--project", str(project), "--run-id", master_path.parent.name,
        "--runtime-config", str(tmp_path / "db.json"),
    ])
    result_events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 0
    stage, command = calls[0]
    assert stage == "db-scenarios"
    assert command[command.index("--junit-xml") + 1] == str(master_path.parent / "db-scenario-junit.xml")
    report = next(event["path"] for event in result_events if event.get("kind") == "html_report")
    assert Path(report).is_file()


def test_db_workflow_writes_master_artifact_before_execution(monkeypatch, tmp_path, capsys):
    project = _write_project(tmp_path, db_scenarios=True)
    (tmp_path / "openapi.json").write_text(json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "fixture", "version": "1"},
        "paths": {"/users/{id}": {
            "get": {"operationId": "getUser", "responses": {"200": {"description": "ok"}}}
        }},
    }), encoding="utf-8")
    (tmp_path / "scenarios.yaml").write_text("""
scenarios:
  - name: read user
    request:
      operationId: getUser
      path_params: {id: 1}
    response_check:
      expect: {status: 200}
""", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        cli,
        "run_command",
        lambda stage, command, emit: calls.append(stage) or StageResult.passed(),
    )

    code = cli.main([
        "run-db-scenarios", "--project", str(project), "--runtime-config", str(tmp_path / "db.json")
    ])

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert calls == ["db-scenarios"]
    artifact = next(event for event in events if event.get("kind") == "case_master_json")
    master = json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))
    assert master["cases"][0]["kind"] == "db-scenario"
    assert master["cases"][0]["reviewStatus"] == "draft"
    assert (Path(artifact["path"]).parent / "case-spec.xlsx").exists()
    assert (Path(artifact["path"]).parent / "report.html").exists()

def test_cli_script_entrypoint_imports_workflow_package_from_repository_root():
    import os
    import subprocess
    import sys

    from workflow.commands import REPO_ROOT

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "workflow" / "cli.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert "prepare-contract" in result.stdout


def _write_exploratory_project(tmp_path, selected_operations=("getUser",)):
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps({
        "openapi": "3.0.3", "info": {"title": "fixture", "version": "1"},
        "paths": {"/users": {"get": {"operationId": "getUser", "responses": {"200": {"description": "ok"}}}}},
    }), encoding="utf-8")
    project_path = tmp_path / "project.json"
    project_path.write_text(json.dumps({
        "schemaVersion": 1,
        "name": "explore",
        "openapiPath": "openapi.json",
        "baseUrl": "http://127.0.0.1:8080",
        "outputDir": "artifacts",
        "selectedOperations": list(selected_operations),
    }), encoding="utf-8")
    return project_path


def test_run_schemathesis_requires_selected_operations_before_execution(monkeypatch, tmp_path, capsys):
    project = _write_exploratory_project(tmp_path, selected_operations=())
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda *args, **kwargs: calls.append(args))

    code = cli.main(["run-schemathesis", "--project", str(project)])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == []
    assert any("対象API" in event.get("message", "") for event in events)


def test_run_schemathesis_reports_missing_local_dependency_without_api_request(
    monkeypatch, tmp_path, capsys,
):
    project = _write_exploratory_project(tmp_path)
    calls = []
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli, "run_command", lambda *args, **kwargs: calls.append(args))

    code = cli.main(["run-schemathesis", "--project", str(project)])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 3
    assert calls == []
    assert any("requirements-schemathesis.txt" in event.get("message", "") for event in events)


def test_run_schemathesis_keeps_local_junit_and_html_on_test_failure(monkeypatch, tmp_path, capsys):
    project = _write_exploratory_project(tmp_path)
    calls = []

    def fake_run(stage, command, emit, **kwargs):
        calls.append((stage, command, kwargs))
        junit = Path(command[command.index("--report-junit-path") + 1])
        junit.write_text(
            '<testsuites><testsuite><testcase name="GET /users">'
            '<failure message="500">bad response</failure></testcase></testsuite></testsuites>',
            encoding="utf-8",
        )
        return StageResult.failed(1)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "schemathesis.exe")
    monkeypatch.setattr(cli, "run_command", fake_run)

    code = cli.main(["run-schemathesis", "--project", str(project)])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]

    assert code == 1
    assert len(calls) == 1
    stage, command, kwargs = calls[0]
    assert stage == "schemathesis"
    assert command[command.index("--include-method") + 1] == "GET"
    assert "--include-method" in command
    assert kwargs["warning_exit_codes"] == ()
    config_path = Path(command[command.index("--config-file") + 1])
    config_text = config_path.read_text(encoding="utf-8")
    assert "unexpected-methods = []" in config_text
    assert "[checks.ignored_auth]\nenabled = true" in config_text
    assert {event["kind"] for event in events if event["type"] == "artifact"} == {
        "schemathesis_manifest", "schemathesis_junit", "schemathesis_html", "schemathesis_config",
    }
    manifest = Path(next(event["path"] for event in events if event.get("kind") == "schemathesis_manifest"))
    assert json.loads(manifest.read_text(encoding="utf-8"))["methods"] == ["GET"]
    report = Path(next(event["path"] for event in events if event.get("kind") == "schemathesis_html"))
    assert "bad response" in report.read_text(encoding="utf-8")


def test_run_schemathesis_token_exists_only_in_child_environment_and_is_redacted(
    monkeypatch, tmp_path, capsys,
):
    project = _write_exploratory_project(tmp_path)
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"login_url": "/login", "method": "POST"}), encoding="utf-8")
    token = "secret-token-123"
    calls = []

    def fake_run(stage, command, emit, **kwargs):
        calls.append((command, kwargs))
        junit = Path(command[command.index("--report-junit-path") + 1])
        junit.write_text(f'<testsuites><testsuite><testcase name="x"><failure>{token}</failure></testcase></testsuite></testsuites>', encoding="utf-8")
        cassette = command[command.index("--report-vcr-path") + 1]
        Path(cassette).write_text(f"Authorization: {token}\n", encoding="utf-8")
        return StageResult.failed(1)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "schemathesis.exe")
    monkeypatch.setattr(cli, "load_auth_config", lambda path: {"login_url": "/login", "method": "POST"})
    monkeypatch.setattr(cli, "perform_login", lambda base_url, config: token)
    monkeypatch.setattr(cli, "build_auth_header", lambda token, config: ("Authorization", f"Bearer {token}"))
    monkeypatch.setattr(cli, "run_command", fake_run)

    code = cli.main([
        "run-schemathesis", "--project", str(project), "--auth-config", str(auth), "--save-cassette",
    ])
    output = capsys.readouterr().out

    assert code == 1
    command, kwargs = calls[0]
    assert token not in " ".join(command)
    assert kwargs["env"]["API_TESTER_SCHEMATHESIS_HEADER"] == f"Bearer {token}"
    assert kwargs["redact_values"] == (token, f"Bearer {token}")
    config_path = Path(command[command.index("--config-file") + 1])
    config_text = config_path.read_text(encoding="utf-8")
    assert "${API_TESTER_SCHEMATHESIS_HEADER}" in config_text
    assert "unexpected-methods = []" in config_text
    assert "[checks.ignored_auth]\nenabled = true" in config_text
    assert token not in config_text
    assert token not in output
    manifest_path = next(Path(path) for path in _artifact_paths_from_output(output) if path.endswith("manifest.json"))
    assert token not in manifest_path.read_text(encoding="utf-8")
    for result_path in (Path(command[command.index("--report-junit-path") + 1]), Path(command[command.index("--report-vcr-path") + 1])):
        assert token not in result_path.read_text(encoding="utf-8")


def _artifact_paths_from_output(output):
    return [event["path"] for line in output.splitlines() if (event := json.loads(line)).get("type") == "artifact"]
