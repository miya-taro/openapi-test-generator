import json

import pytest

from workflow.models import ProjectConfig, ProjectConfigError
from workflow.project_store import load_project, save_project


def _project_data(**overrides):
    data = {
        "schemaVersion": 1,
        "name": "sample",
        "openapiPath": "openapi.json",
        "baseUrl": "http://vm.local/api",
        "outputDir": "artifacts",
    }
    data.update(overrides)
    return data


def test_load_project_resolves_paths_from_project_file(tmp_path):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "openapi.json").write_text(
        '{"openapi":"3.0.3","paths":{}}', encoding="utf-8"
    )
    path = project / "project.json"
    path.write_text(json.dumps(_project_data()), encoding="utf-8")

    config = load_project(path)

    assert config.project_dir == project.resolve()
    assert config.openapi_path == (project / "openapi.json").resolve()
    assert config.output_dir == (project / "artifacts").resolve()


@pytest.mark.parametrize(
    "secret_key", ["password", "clientSecret", "accessToken", "cookie", "authorization"]
)
def test_load_project_rejects_secret_keys(tmp_path, secret_key):
    path = tmp_path / "project.json"
    path.write_text(
        json.dumps(_project_data(**{secret_key: "secret"})), encoding="utf-8"
    )

    with pytest.raises(ProjectConfigError, match="秘密情報"):
        load_project(path)


def test_load_project_rejects_unknown_keys(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps(_project_data(unknownOption=True)), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="未対応の項目"):
        load_project(path)


def test_save_then_load_preserves_project_config(tmp_path):
    project_file = tmp_path / "project.json"
    config = ProjectConfig(
        schema_version=1,
        name="orders",
        project_dir=tmp_path.resolve(),
        openapi_path=(tmp_path / "openapi.json").resolve(),
        base_url="http://vm.local/api",
        output_dir=(tmp_path / "artifacts").resolve(),
        selected_operations=("getOrder", "createOrder"),
    )

    save_project(config, project_file)

    assert load_project(project_file) == config
    saved = json.loads(project_file.read_text(encoding="utf-8"))
    assert saved["openapiPath"] == "openapi.json"
    assert saved["outputDir"] == "artifacts"


def test_load_project_rejects_wrong_schema_version(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps(_project_data(schemaVersion=99)), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="schemaVersion"):
        load_project(path)


def test_load_project_rejects_non_http_base_url(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps(_project_data(baseUrl="file:///tmp/api")), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="Base URL"):
        load_project(path)


def test_optional_paths_and_operations_round_trip(tmp_path):
    config = ProjectConfig(
        schema_version=1,
        name="orders",
        project_dir=tmp_path.resolve(),
        openapi_path=(tmp_path / "openapi.json").resolve(),
        base_url="https://vm.local/api",
        output_dir=(tmp_path / "artifacts").resolve(),
        selected_operations=("getOrder",),
        setup_sql_path=(tmp_path / "setup.sql").resolve(),
        teardown_sql_path=(tmp_path / "teardown.sql").resolve(),
        db_scenarios_path=(tmp_path / "scenarios.yaml").resolve(),
    )
    path = tmp_path / "project.json"

    save_project(config, path)

    assert load_project(path) == config
