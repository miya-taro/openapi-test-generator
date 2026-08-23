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
