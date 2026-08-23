"""MappingGenTab / SetupSqlGenTab / ScenarioGenTab（DB準備タブ群）のコマンド組み立てを検証する。

test_app.py と同じ方式（run_streamed をフェイクに差し替え、コマンド引数だけ検証）。
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication

import app as app_module
from settings import DEFAULTS

_app = QApplication.instance() or QApplication([])


def _wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        _app.processEvents()
        time.sleep(0.01)
    return False


@pytest.fixture
def captured_cmds(monkeypatch):
    calls = []

    def fake_run_streamed(cmd, log_queue, **kwargs):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run_streamed)
    return calls


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setattr(app_module, "load_settings", lambda: dict(DEFAULTS))
    w = app_module.MainWindow()
    yield w
    for tab in w._all_tabs:
        if hasattr(tab, "panel"):
            tab.panel.stop()
        if hasattr(tab, "connectivity_row"):
            tab.connectivity_row.stop()


# ---------- MappingGenTab ----------


def test_mapping_gen_requires_openapi_and_config(window, captured_cmds, monkeypatch):
    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    window.mapping_gen_tab.on_run()
    assert len(shown) == 1
    assert captured_cmds == []


def test_mapping_gen_builds_expected_command(window, captured_cmds, tmp_path):
    openapi_path = str(tmp_path / "openapi.json")
    config_path = str(tmp_path / "config.json")
    window.mapping_gen_tab.openapi_field.set(openapi_path)
    window.mapping_gen_tab.config_field.set(config_path)
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    cmd = captured_cmds[0]
    assert str(app_module.GENERATE_MAPPING_PY) in cmd
    assert openapi_path in cmd
    assert cmd[cmd.index("--config") + 1] == config_path
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / "mapping.yaml.generated")
    assert cmd[cmd.index("--schema") + 1] == "public"  # settings既定値


def test_mapping_gen_omits_schema_flag_when_blank(window, captured_cmds, tmp_path):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))
    window.mapping_gen_tab.schema_field.set("")

    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    assert "--schema" not in captured_cmds[0]


def test_mapping_gen_fields_persisted_to_settings(window, tmp_path):
    openapi_path = str(tmp_path / "openapi.json")
    window.mapping_gen_tab.openapi_field.set(openapi_path)
    window.mapping_gen_tab.save_fields()
    assert window.settings["mapgen_openapi_path"] == openapi_path


def test_mapping_gen_result_path_set_only_on_success(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))
    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 1)

    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.panel.status_label.text() != "実行中...")
    assert window.mapping_gen_tab.panel.result_path is None


def test_mapping_gen_preview_populated_on_success(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    def fake_run(cmd, q, **kwargs):
        (tmp_path / "mapping.yaml.generated").write_text(
            "operations:\n  createUser:\n    table: users  # 確信度: 高\n", encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run)
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.preview_edit.toPlainText() != "")
    assert "確信度: 高" in window.mapping_gen_tab.preview_edit.toPlainText()


def test_mapping_gen_preview_cleared_on_failure(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))
    window.mapping_gen_tab.preview_edit.setPlainText("stale content")

    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 1)
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.panel.status_label.text() != "実行中...")
    assert window.mapping_gen_tab.preview_edit.toPlainText() == ""


def test_sqlgen_preview_populated_on_success(window, tmp_path, monkeypatch):
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))

    def fake_run(cmd, q, **kwargs):
        (tmp_path / "setup.sql.generated").write_text("INSERT INTO users (id) VALUES (1);\n", encoding="utf-8")
        (tmp_path / "teardown.sql.generated").write_text("TRUNCATE TABLE users;\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run)
    window.sql_gen_tab.on_run()
    assert _wait_for(lambda: window.sql_gen_tab.preview_edit.toPlainText() != "")
    assert "INSERT INTO users" in window.sql_gen_tab.preview_edit.toPlainText()


def test_scengen_preview_populated_on_success(window, tmp_path, monkeypatch):
    window.scenario_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.scenario_gen_tab.mapping_field.set(str(tmp_path / "mapping.yaml"))
    window.scenario_gen_tab.output_dir_field.set(str(tmp_path))

    def fake_run(cmd, q, **kwargs):
        (tmp_path / "scenarios.generated.yaml").write_text("scenarios:\n  list: []\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run)
    window.scenario_gen_tab.on_run()
    assert _wait_for(lambda: window.scenario_gen_tab.preview_edit.toPlainText() != "")
    assert "scenarios" in window.scenario_gen_tab.preview_edit.toPlainText()


def test_mapping_gen_prompts_before_overwriting_existing_output(window, captured_cmds, tmp_path, monkeypatch):
    (tmp_path / "mapping.yaml.generated").write_text("existing", encoding="utf-8")
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    asked = []
    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: (asked.append(a), app_module.QMessageBox.StandardButton.No)[1],
    )
    window.mapping_gen_tab.on_run()
    assert len(asked) == 1
    assert captured_cmds == []  # Noを選んだので実行されない


def test_mapping_gen_runs_when_overwrite_confirmed(window, captured_cmds, tmp_path, monkeypatch):
    (tmp_path / "mapping.yaml.generated").write_text("existing", encoding="utf-8")
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: app_module.QMessageBox.StandardButton.Yes,
    )
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)


def test_mapping_gen_no_prompt_when_output_does_not_exist(window, captured_cmds, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    asked = []
    monkeypatch.setattr(app_module.QMessageBox, "question", lambda *a, **k: asked.append(a))
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)
    assert asked == []


def test_sqlgen_prompts_before_overwriting_either_output_file(window, captured_cmds, tmp_path, monkeypatch):
    (tmp_path / "teardown.sql.generated").write_text("existing", encoding="utf-8")  # setupは無い方
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))

    asked = []
    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: (asked.append(a), app_module.QMessageBox.StandardButton.No)[1],
    )
    window.sql_gen_tab.on_run()
    assert len(asked) == 1
    assert captured_cmds == []


def test_scengen_prompts_before_overwriting_existing_output(window, captured_cmds, tmp_path, monkeypatch):
    (tmp_path / "scenarios.generated.yaml").write_text("existing", encoding="utf-8")
    window.scenario_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.scenario_gen_tab.mapping_field.set(str(tmp_path / "mapping.yaml"))
    window.scenario_gen_tab.output_dir_field.set(str(tmp_path))

    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: app_module.QMessageBox.StandardButton.No,
    )
    window.scenario_gen_tab.on_run()
    assert captured_cmds == []


# ---------- 入力を確認ボタン ----------


def test_mapping_gen_validate_button_calls_expected_validators(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))

    shown = []
    monkeypatch.setattr(app_module, "_show_validation", lambda parent, title, checks: shown.append(checks))
    window.mapping_gen_tab.on_validate()
    assert len(shown) == 1
    labels = [label for label, _ in shown[0]]
    assert labels == ["openapi.json", "DB接続設定"]


def test_sqlgen_validate_button_calls_expected_validators(window, tmp_path, monkeypatch):
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))

    shown = []
    monkeypatch.setattr(app_module, "_show_validation", lambda parent, title, checks: shown.append(checks))
    window.sql_gen_tab.on_validate()
    assert shown[0] == [("DB接続設定", app_module.validators.validate_db_config(str(tmp_path / "config.json")))]


def test_scengen_validate_button_calls_expected_validators(window, tmp_path, monkeypatch):
    window.scenario_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.scenario_gen_tab.mapping_field.set(str(tmp_path / "mapping.yaml"))

    shown = []
    monkeypatch.setattr(app_module, "_show_validation", lambda parent, title, checks: shown.append(checks))
    window.scenario_gen_tab.on_validate()
    labels = [label for label, _ in shown[0]]
    assert labels == ["openapi.json", "mapping.yaml"]


# ---------- SetupSqlGenTab ----------


def test_sqlgen_requires_config(window, captured_cmds, monkeypatch):
    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    window.sql_gen_tab.on_run()
    assert len(shown) == 1
    assert captured_cmds == []


def test_sqlgen_builds_expected_command(window, captured_cmds, tmp_path):
    config_path = str(tmp_path / "config.json")
    window.sql_gen_tab.config_field.set(config_path)
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))

    window.sql_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    cmd = captured_cmds[0]
    assert str(app_module.GENERATE_SETUP_SQL_PY) in cmd
    assert cmd[cmd.index("--config") + 1] == config_path
    assert cmd[cmd.index("--setup-output") + 1] == str(tmp_path / "setup.sql.generated")
    assert cmd[cmd.index("--teardown-output") + 1] == str(tmp_path / "teardown.sql.generated")


def test_sqlgen_includes_tables_flag_when_set(window, captured_cmds, tmp_path):
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))
    window.sql_gen_tab.tables_field.set("users,orders")

    window.sql_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    cmd = captured_cmds[0]
    assert cmd[cmd.index("--tables") + 1] == "users,orders"


def test_sqlgen_omits_tables_flag_when_blank(window, captured_cmds, tmp_path):
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))

    window.sql_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    assert "--tables" not in captured_cmds[0]


def test_sqlgen_fields_persisted_to_settings(window, tmp_path):
    window.sql_gen_tab.tables_field.set("users")
    window.sql_gen_tab.save_fields()
    assert window.settings["sqlgen_tables"] == "users"


# ---------- ScenarioGenTab ----------


def test_scengen_requires_openapi_and_mapping(window, captured_cmds, monkeypatch):
    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    window.scenario_gen_tab.on_run()
    assert len(shown) == 1
    assert captured_cmds == []


def test_scengen_builds_expected_command(window, captured_cmds, tmp_path):
    openapi_path = str(tmp_path / "openapi.json")
    mapping_path = str(tmp_path / "mapping.yaml")
    window.scenario_gen_tab.openapi_field.set(openapi_path)
    window.scenario_gen_tab.mapping_field.set(mapping_path)
    window.scenario_gen_tab.output_dir_field.set(str(tmp_path))

    window.scenario_gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    cmd = captured_cmds[0]
    assert str(app_module.GENERATE_DB_SCENARIOS_PY) in cmd
    assert openapi_path in cmd
    assert mapping_path in cmd
    assert cmd[cmd.index("-o") + 1] == str(tmp_path / "scenarios.generated.yaml")


def test_scengen_fields_persisted_to_settings(window, tmp_path):
    mapping_path = str(tmp_path / "mapping.yaml")
    window.scenario_gen_tab.mapping_field.set(mapping_path)
    window.scenario_gen_tab.save_fields()
    assert window.settings["scengen_mapping_path"] == mapping_path


# ---------- LogPanel exit_code_meanings override ----------


def test_generator_tab_uses_custom_exit_code_message_on_success(window, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 0)
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.panel.status_label.text() == "OK：生成完了")


def test_generator_tab_uses_custom_exit_code_message_on_failure(window, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 1)
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.panel.status_label.text() == "ERROR：生成に失敗しました")
