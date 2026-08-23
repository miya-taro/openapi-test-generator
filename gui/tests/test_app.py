"""app.py の各タブが組み立てるサブプロセスコマンドを検証する。

実際のサブプロセス実行（run_streamed）はフェイクに差し替え、
「何を・どんな引数で」呼ぶかだけを検証する。QApplication はプロセス内で使い回す
（PySide6 は同一プロセス内でインスタンスを複数作れないため）。
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

    def fake_run_streamed(cmd, log_queue):
        calls.append(cmd)
        return 0

    monkeypatch.setattr(app_module, "run_streamed", fake_run_streamed)
    return calls


@pytest.fixture
def window(tmp_path, monkeypatch):
    # 実ユーザーの保存済み設定ファイルを読み書きしないよう、存在しないパスに差し替える
    # （load_settings はファイルが無ければ DEFAULTS を返す。書き込みは closeEvent 経由のみで、
    # このテストでは closeEvent を呼ばないため実際には書き込まれないが、念のため隔離する）。
    monkeypatch.setattr(app_module, "load_settings", lambda: dict(DEFAULTS))
    w = app_module.MainWindow()
    yield w
    w.gen_tab.panel.stop()
    w.db_tab.panel.stop()


# ---------- GenerateRunTab ----------


def test_gen_tab_omits_auth_config_when_blank(window, captured_cmds, tmp_path):
    window.gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.gen_tab.base_url_field.set("http://localhost")
    window.gen_tab.output_dir_field.set(str(tmp_path))
    window.gen_tab.auth_config_field.set("")

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    assert "--auth-config" not in run_cmd


def test_gen_tab_includes_auth_config_when_set(window, captured_cmds, tmp_path):
    auth_path = str(tmp_path / "auth.json")
    window.gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.gen_tab.base_url_field.set("http://localhost")
    window.gen_tab.output_dir_field.set(str(tmp_path))
    window.gen_tab.auth_config_field.set(auth_path)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    idx = run_cmd.index("--auth-config")
    assert run_cmd[idx + 1] == auth_path


def test_gen_tab_auth_config_persisted_to_settings(window, tmp_path):
    auth_path = str(tmp_path / "auth.json")
    window.gen_tab.auth_config_field.set(auth_path)
    window.gen_tab.save_fields()
    assert window.settings["gen_auth_config_path"] == auth_path


def test_gen_tab_dry_run_unchecked_by_default_omits_flag(window, captured_cmds, tmp_path):
    window.gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.gen_tab.base_url_field.set("http://localhost")
    window.gen_tab.output_dir_field.set(str(tmp_path))
    assert window.gen_tab.dry_run_checkbox.isChecked() is False

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    assert "--dry-run" not in captured_cmds[1]


def test_gen_tab_dry_run_checked_adds_flag_to_run_step_only(window, captured_cmds, tmp_path):
    window.gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.gen_tab.base_url_field.set("http://localhost")
    window.gen_tab.output_dir_field.set(str(tmp_path))
    window.gen_tab.dry_run_checkbox.setChecked(True)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    gen_cmd, run_cmd = captured_cmds[0], captured_cmds[1]
    assert "--dry-run" not in gen_cmd  # 生成ステップ自体はHTTPを送らないため対象外
    assert "--dry-run" in run_cmd


def test_gen_tab_dry_run_persisted_to_settings(window):
    window.gen_tab.dry_run_checkbox.setChecked(True)
    window.gen_tab.save_fields()
    assert window.settings["gen_dry_run"] is True


def _fill_gen_tab_required(window, tmp_path):
    window.gen_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.gen_tab.base_url_field.set("http://localhost")
    window.gen_tab.output_dir_field.set(str(tmp_path))


def test_gen_tab_setup_without_config_shows_error_and_does_not_run(window, captured_cmds, tmp_path, monkeypatch):
    _fill_gen_tab_required(window, tmp_path)
    window.gen_tab.setup_field.set(str(tmp_path / "setup.sql"))
    window.gen_tab.config_field.set("")

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))

    window.gen_tab.on_run()
    assert len(shown) == 1
    assert captured_cmds == []


def test_gen_tab_teardown_without_config_shows_error_and_does_not_run(window, captured_cmds, tmp_path, monkeypatch):
    _fill_gen_tab_required(window, tmp_path)
    window.gen_tab.teardown_field.set(str(tmp_path / "teardown.sql"))
    window.gen_tab.config_field.set("")

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))

    window.gen_tab.on_run()
    assert len(shown) == 1
    assert captured_cmds == []


def test_gen_tab_setup_with_config_runs_and_passes_all_three_flags(window, captured_cmds, tmp_path):
    _fill_gen_tab_required(window, tmp_path)
    config_path = str(tmp_path / "config.json")
    setup_path = str(tmp_path / "setup.sql")
    teardown_path = str(tmp_path / "teardown.sql")
    window.gen_tab.config_field.set(config_path)
    window.gen_tab.setup_field.set(setup_path)
    window.gen_tab.teardown_field.set(teardown_path)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    assert run_cmd[run_cmd.index("--config") + 1] == config_path
    assert run_cmd[run_cmd.index("--setup") + 1] == setup_path
    assert run_cmd[run_cmd.index("--teardown") + 1] == teardown_path


def test_gen_tab_config_alone_without_setup_or_teardown_is_allowed(window, captured_cmds, tmp_path):
    # --config だけの指定はCLI側も許容している（--setup/--teardownの時だけ必須）
    _fill_gen_tab_required(window, tmp_path)
    config_path = str(tmp_path / "config.json")
    window.gen_tab.config_field.set(config_path)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    assert "--config" in run_cmd
    assert "--setup" not in run_cmd
    assert "--teardown" not in run_cmd


def test_gen_tab_full_body_and_fail_fast_omitted_by_default(window, captured_cmds, tmp_path):
    _fill_gen_tab_required(window, tmp_path)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    assert "--full-body" not in run_cmd
    assert "--fail-fast" not in run_cmd


def test_gen_tab_full_body_and_fail_fast_included_when_checked(window, captured_cmds, tmp_path):
    _fill_gen_tab_required(window, tmp_path)
    window.gen_tab.full_body_checkbox.setChecked(True)
    window.gen_tab.fail_fast_checkbox.setChecked(True)

    window.gen_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 2)

    run_cmd = captured_cmds[1]
    assert "--full-body" in run_cmd
    assert "--fail-fast" in run_cmd


def test_gen_tab_new_fields_persisted_to_settings(window, tmp_path):
    config_path = str(tmp_path / "config.json")
    setup_path = str(tmp_path / "setup.sql")
    teardown_path = str(tmp_path / "teardown.sql")
    window.gen_tab.config_field.set(config_path)
    window.gen_tab.setup_field.set(setup_path)
    window.gen_tab.teardown_field.set(teardown_path)
    window.gen_tab.full_body_checkbox.setChecked(True)
    window.gen_tab.fail_fast_checkbox.setChecked(True)
    window.gen_tab.save_fields()

    assert window.settings["gen_config_path"] == config_path
    assert window.settings["gen_setup_path"] == setup_path
    assert window.settings["gen_teardown_path"] == teardown_path
    assert window.settings["gen_full_body"] is True
    assert window.settings["gen_fail_fast"] is True


# ---------- DBScenarioTab ----------


def test_db_tab_omits_auth_config_when_blank(window, captured_cmds, tmp_path):
    window.db_tab.scenario_field.set(str(tmp_path / "scenarios.yaml"))
    window.db_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.db_tab.config_field.set(str(tmp_path / "config.json"))
    window.db_tab.base_url_field.set("http://localhost")
    window.db_tab.auth_config_field.set("")

    window.db_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    assert "--auth-config" not in captured_cmds[0]


def test_db_tab_includes_auth_config_when_set(window, captured_cmds, tmp_path):
    auth_path = str(tmp_path / "auth.json")
    window.db_tab.scenario_field.set(str(tmp_path / "scenarios.yaml"))
    window.db_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.db_tab.config_field.set(str(tmp_path / "config.json"))
    window.db_tab.base_url_field.set("http://localhost")
    window.db_tab.auth_config_field.set(auth_path)

    window.db_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    cmd = captured_cmds[0]
    idx = cmd.index("--auth-config")
    assert cmd[idx + 1] == auth_path


def test_db_tab_auth_config_persisted_to_settings(window, tmp_path):
    auth_path = str(tmp_path / "auth.json")
    window.db_tab.auth_config_field.set(auth_path)
    window.db_tab.save_fields()
    assert window.settings["db_auth_config_path"] == auth_path


def test_db_tab_dry_run_unchecked_by_default_omits_flag(window, captured_cmds, tmp_path):
    window.db_tab.scenario_field.set(str(tmp_path / "scenarios.yaml"))
    window.db_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.db_tab.config_field.set(str(tmp_path / "config.json"))
    window.db_tab.base_url_field.set("http://localhost")
    assert window.db_tab.dry_run_checkbox.isChecked() is False

    window.db_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    assert "--dry-run" not in captured_cmds[0]


def test_db_tab_dry_run_checked_adds_flag(window, captured_cmds, tmp_path):
    window.db_tab.scenario_field.set(str(tmp_path / "scenarios.yaml"))
    window.db_tab.openapi_field.set(str(tmp_path / "openapi.json"))
    window.db_tab.config_field.set(str(tmp_path / "config.json"))
    window.db_tab.base_url_field.set("http://localhost")
    window.db_tab.dry_run_checkbox.setChecked(True)

    window.db_tab.on_run()
    assert _wait_for(lambda: len(captured_cmds) >= 1)

    assert "--dry-run" in captured_cmds[0]


def test_db_tab_dry_run_persisted_to_settings(window):
    window.db_tab.dry_run_checkbox.setChecked(True)
    window.db_tab.save_fields()
    assert window.settings["db_dry_run"] is True
