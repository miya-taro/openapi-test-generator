
import pytest

from workflow.schemathesis_runner import build_schemathesis_command


def test_builds_local_get_only_command_with_reproducible_bounded_run(tmp_path):
    command = build_schemathesis_command(
        "schemathesis.exe",
        tmp_path / "openapi.json",
        "http://127.0.0.1:8080",
        tmp_path / "junit.xml",
        None,
        include_mutating=False,
        max_examples=10,
        selected_operations=("listUsers", "getUser"),
        config_path=tmp_path / "schemathesis.toml",
    )

    assert command[:4] == [
        "schemathesis.exe", "--config-file", str(tmp_path / "schemathesis.toml"), "run",
    ]
    assert command[command.index("--url") + 1] == "http://127.0.0.1:8080"
    assert command[command.index("--include-method") + 1] == "GET"
    assert "--include-operation-id=listUsers" in command
    assert "--include-operation-id=getUser" in command
    assert command[command.index("--max-examples") + 1] == "10"
    assert command[command.index("--seed") + 1] == "1"
    assert command[command.index("--generation-database") + 1] == "none"
    assert command[command.index("--report-junit-path") + 1] == str(tmp_path / "junit.xml")
    assert "--include-method" in command
    assert "--report-vcr-path" not in command


def test_mutating_methods_are_only_unfiltered_when_explicitly_enabled(tmp_path):
    command = build_schemathesis_command(
        "schemathesis", tmp_path / "openapi.json", "http://localhost:8080",
        tmp_path / "junit.xml", tmp_path / "cassette.yaml",
        include_mutating=True, max_examples=3,
    )

    assert "--include-method" not in command
    assert command[command.index("--report") + 1] == "junit,vcr"
    assert command[command.index("--report-vcr-path") + 1] == str(tmp_path / "cassette.yaml")


@pytest.mark.parametrize("value", [0, -1, 101, True, 1.5])
def test_rejects_unbounded_or_non_integer_example_counts(tmp_path, value):
    with pytest.raises(ValueError, match="1..100"):
        build_schemathesis_command(
            "schemathesis", tmp_path / "openapi.json", "http://localhost",
            tmp_path / "junit.xml", None, include_mutating=False, max_examples=value,
        )


def test_rejects_blank_or_duplicate_operation_ids(tmp_path):
    with pytest.raises(ValueError, match="operation ID"):
        build_schemathesis_command(
            "schemathesis", tmp_path / "openapi.json", "http://localhost",
            tmp_path / "junit.xml", None, include_mutating=False, max_examples=1,
            selected_operations=("getUser", "getUser", " "),
        )


def test_operation_id_is_kept_inside_its_option_value(tmp_path):
    command = build_schemathesis_command(
        "schemathesis", tmp_path / "openapi.json", "http://localhost",
        tmp_path / "junit.xml", None, include_mutating=False, max_examples=1,
        selected_operations=("--seed",),
    )

    assert "--include-operation-id=--seed" in command
    assert command.count("--seed") == 1


def test_rejects_credentials_embedded_in_base_url(tmp_path):
    with pytest.raises(ValueError, match="ユーザー名やパスワード"):
        build_schemathesis_command(
            "schemathesis", tmp_path / "openapi.json", "http://user:password@localhost",
            tmp_path / "junit.xml", None, include_mutating=False, max_examples=1,
        )
