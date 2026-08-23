"""実行中プロセスのキャンセル、GUI終了時の確認、DB接続確認（ConnectivityCheckRow）を検証する。

キャンセル系は実際にsubprocessを起動してterminate()させるところまで確認する
（他のGUIテストのようにrun_streamedをフェイクに差し替えない）。
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

import app as app_module
from process_runner import run_streamed
from settings import DEFAULTS

_app = QApplication.instance() or QApplication([])

_SLEEP_CMD = [sys.executable, "-c", "import time; time.sleep(30)"]


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        _app.processEvents()
        time.sleep(0.01)
    return False


def _start_real_sleep_job(panel: "app_module.LogPanel") -> None:
    def worker():
        code = run_streamed(_SLEEP_CMD, panel.log_queue, on_start=panel.register_process)
        panel.finish(code, None)

    panel.start(worker)


@pytest.fixture
def window(monkeypatch):
    monkeypatch.setattr(app_module, "load_settings", lambda: dict(DEFAULTS))
    monkeypatch.setattr(app_module, "save_settings", lambda s: None)
    w = app_module.MainWindow()
    yield w
    for tab in w._all_tabs:
        if hasattr(tab, "panel"):
            tab.panel.cancel()
            tab.panel.stop()
        if hasattr(tab, "connectivity_row"):
            tab.connectivity_row.stop()
        if hasattr(tab, "stop"):
            tab.stop()


# ---------- LogPanel: キャンセルボタン ----------


def test_cancel_button_disabled_before_run():
    panel = app_module.LogPanel("実行", lambda: None)
    assert panel.cancel_button.isEnabled() is False
    panel.stop()


def test_cancel_button_enabled_while_running_disabled_after_finish():
    panel = app_module.LogPanel("実行", lambda: None)
    _start_real_sleep_job(panel)
    assert _wait_for(lambda: panel.cancel_button.isEnabled() is True)
    # cancel_button.isEnabled()はstart()内で即座にTrueになるが、current_processの登録は
    # バックグラウンドスレッド側で非同期に行われるため、is_running()で実際の起動を待つ
    # （でないとcancel()が「まだ何も実行していない」扱いのno-opになってしまう）。
    assert _wait_for(lambda: panel.is_running())

    panel.cancel()
    assert _wait_for(lambda: panel.cancel_button.isEnabled() is False, timeout=5)
    panel.stop()


def test_cancel_terminates_real_subprocess_and_updates_status():
    panel = app_module.LogPanel("実行", lambda: None)
    _start_real_sleep_job(panel)
    assert _wait_for(lambda: panel.is_running())

    panel.cancel()

    assert _wait_for(lambda: not panel.is_running(), timeout=5)
    assert _wait_for(lambda: panel.status_label.text() == "キャンセルしました", timeout=5)
    panel.stop()


def test_cancel_when_nothing_running_is_a_no_op():
    panel = app_module.LogPanel("実行", lambda: None)
    panel.cancel()  # 何も実行していない状態で呼んでも例外にならない
    assert panel.status_label.text() == ""
    panel.stop()


# ---------- MainWindow.closeEvent: 実行中の確認 ----------


def test_close_event_no_prompt_when_nothing_running(window, monkeypatch):
    asked = []
    monkeypatch.setattr(app_module.QMessageBox, "question", lambda *a, **k: asked.append(a))

    event = QCloseEvent()
    window.closeEvent(event)

    assert asked == []
    assert event.isAccepted()


def test_close_event_ignores_close_when_user_declines(window, monkeypatch):
    _start_real_sleep_job(window.gen_tab.panel)
    assert _wait_for(lambda: window.gen_tab.panel.is_running())

    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: app_module.QMessageBox.StandardButton.No,
    )
    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted()
    assert window.gen_tab.panel.is_running()  # Noを選んだので動き続けている


def test_close_event_proceeds_and_kills_process_when_user_confirms(window, monkeypatch):
    _start_real_sleep_job(window.gen_tab.panel)
    assert _wait_for(lambda: window.gen_tab.panel.is_running())

    monkeypatch.setattr(
        app_module.QMessageBox, "question",
        lambda *a, **k: app_module.QMessageBox.StandardButton.Yes,
    )
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert _wait_for(lambda: not window.gen_tab.panel.is_running(), timeout=5)


# ---------- ConnectivityCheckRow ----------


def test_connectivity_row_blank_path_shows_message_without_running_check(monkeypatch):
    called = []
    monkeypatch.setattr(app_module.validators, "check_db_connectivity", lambda p: called.append(p) or "OK")

    row = app_module.ConnectivityCheckRow(lambda: "")
    row.on_check()

    assert "未入力" in row.status_label.text()
    assert called == []
    row.stop()


def test_connectivity_row_runs_check_in_background_and_updates_status(monkeypatch):
    monkeypatch.setattr(app_module.validators, "check_db_connectivity", lambda path: "OK（接続できました）")

    row = app_module.ConnectivityCheckRow(lambda: "dummy_path")
    row.on_check()

    assert _wait_for(lambda: row.status_label.text() == "OK（接続できました）")
    row.stop()


def test_connectivity_row_button_disabled_while_checking_then_reenabled(monkeypatch):
    release = threading.Event()

    def slow_check(path):
        release.wait(timeout=2)
        return "OK"

    monkeypatch.setattr(app_module.validators, "check_db_connectivity", slow_check)

    row = app_module.ConnectivityCheckRow(lambda: "dummy_path")
    row.on_check()
    assert _wait_for(lambda: row.check_button.isEnabled() is False)

    release.set()
    assert _wait_for(lambda: row.check_button.isEnabled() is True)
    row.stop()


def test_connectivity_row_reports_failure_message(monkeypatch):
    monkeypatch.setattr(
        app_module.validators, "check_db_connectivity",
        lambda path: "postgres: NG（接続に失敗しました: connection refused）",
    )

    row = app_module.ConnectivityCheckRow(lambda: "dummy_path")
    row.on_check()

    assert _wait_for(lambda: "NG" in row.status_label.text())
    row.stop()


def test_config_builder_connectivity_row_uses_output_path_field(window, tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    window.config_builder_tab.output_path_field.set(path)

    captured = []
    monkeypatch.setattr(
        app_module.validators, "check_db_connectivity",
        lambda p: (captured.append(p), "OK")[1],
    )
    window.config_builder_tab.connectivity_row.on_check()

    assert _wait_for(lambda: captured == [path])


def test_mapping_gen_connectivity_row_uses_config_field(window, tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    window.mapping_gen_tab.config_field.set(path)

    captured = []
    monkeypatch.setattr(
        app_module.validators, "check_db_connectivity",
        lambda p: (captured.append(p), "OK")[1],
    )
    window.mapping_gen_tab.connectivity_row.on_check()

    assert _wait_for(lambda: captured == [path])
