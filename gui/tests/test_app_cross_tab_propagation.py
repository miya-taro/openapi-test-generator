"""MainWindowの「あるタブの出力を次のタブの入力欄に自動反映する」配線を検証する。"""
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
def window(monkeypatch):
    monkeypatch.setattr(app_module, "load_settings", lambda: dict(DEFAULTS))
    w = app_module.MainWindow()
    yield w
    for tab in w._all_tabs:
        if hasattr(tab, "panel"):
            tab.panel.stop()
        if hasattr(tab, "connectivity_row"):
            tab.connectivity_row.stop()
        if hasattr(tab, "stop"):
            tab.stop()


def test_config_builder_save_propagates_to_all_config_consumers(window, tmp_path):
    tab = window.config_builder_tab
    output_path = tmp_path / "config.json"
    tab.output_path_field.set(str(output_path))
    tab.pg_checkbox.setChecked(True)
    tab.pg_host.set("h")
    tab.pg_port.set("5432")
    tab.pg_dbname.set("d")
    tab.pg_user.set("u")
    tab.pg_password.set("p")

    tab.on_save()

    assert window.mapping_gen_tab.config_field.get() == str(output_path)
    assert window.sql_gen_tab.config_field.get() == str(output_path)
    assert window.db_tab.config_field.get() == str(output_path)
    assert window.gen_tab.config_field.get() == str(output_path)


def test_auth_builder_save_propagates_to_consumers(window, tmp_path):
    tab = window.auth_builder_tab
    output_path = tmp_path / "auth.yaml"
    tab.output_path_field.set(str(output_path))
    tab.login_url_field.set("/login")

    tab.on_save()

    assert window.gen_tab.auth_config_field.get() == str(output_path)
    assert window.db_tab.auth_config_field.get() == str(output_path)


def test_mapping_gen_success_propagates_to_scenario_gen_tab(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 0)
    window.mapping_gen_tab.on_run()

    expected = str(tmp_path / "mapping.yaml.generated")
    assert _wait_for(lambda: window.scenario_gen_tab.mapping_field.get() == expected)


def test_mapping_gen_failure_does_not_propagate(window, tmp_path, monkeypatch):
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 1)
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.panel.status_label.text() != "実行中...")

    assert window.scenario_gen_tab.mapping_field.get() == ""


def test_sqlgen_success_propagates_setup_and_teardown_to_gen_tab(window, tmp_path, monkeypatch):
    window.sql_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.sql_gen_tab.output_dir_field.set(str(tmp_path))

    def fake_run(cmd, q, **kwargs):
        (tmp_path / "setup.sql.generated").write_text("x", encoding="utf-8")
        (tmp_path / "teardown.sql.generated").write_text("y", encoding="utf-8")
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run)
    window.sql_gen_tab.on_run()

    expected_setup = str(tmp_path / "setup.sql.generated")
    expected_teardown = str(tmp_path / "teardown.sql.generated")
    assert _wait_for(lambda: window.gen_tab.setup_field.get() == expected_setup)
    assert window.gen_tab.teardown_field.get() == expected_teardown


def test_scengen_success_propagates_to_db_tab(window, tmp_path, monkeypatch):
    window.scenario_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.scenario_gen_tab.mapping_field.set(str(tmp_path / "mapping.yaml"))
    window.scenario_gen_tab.output_dir_field.set(str(tmp_path))

    monkeypatch.setattr(app_module, "run_streamed", lambda cmd, q, **kwargs: 0)
    window.scenario_gen_tab.on_run()

    expected = str(tmp_path / "scenarios.generated.yaml")
    assert _wait_for(lambda: window.db_tab.scenario_field.get() == expected)


def test_mapping_gen_preview_still_populated_after_propagation_wiring(window, tmp_path, monkeypatch):
    """_chain_on_finishで連結しても、タブ自身のプレビュー更新（元のon_finish）が失われないこと。"""
    window.mapping_gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.mapping_gen_tab.config_field.set(str(tmp_path / "config.json"))
    window.mapping_gen_tab.output_dir_field.set(str(tmp_path))

    def fake_run(cmd, q, **kwargs):
        (tmp_path / "mapping.yaml.generated").write_text("operations: {}\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run)
    window.mapping_gen_tab.on_run()
    assert _wait_for(lambda: window.mapping_gen_tab.preview_edit.toPlainText() != "")
