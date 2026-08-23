#!/usr/bin/env python3
"""openapi-test-gen / openapi-test-run / db_scenario_runner をGUIから操作するデスクトップアプリ（PySide6版）。

既存のCLIツール群をそのままサブプロセスとして呼び出す薄いラッパー。
CLI自体はこれまで通り単独でも使用できる。
"""
from __future__ import annotations
import os
import queue
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QProgressBar, QPlainTextEdit, QMessageBox, QCheckBox,
)

from settings import load_settings, save_settings
from widgets import PathField, TextField
from process_runner import run_streamed, exit_code_meaning
from progress_parser import ProgressTracker

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PY = REPO_ROOT / "src" / "cli.py"
RUNNER_PY = REPO_ROOT / "runner" / "runner.py"
DB_SCENARIO_RUNNER_PY = REPO_ROOT / "runner" / "db_scenario_runner.py"

JSON_FILTER = "JSON (*.json)"
YAML_FILTER = "YAML (*.yaml *.yml)"

STATE_BY_CODE = {0: "ok", 1: "ng", 2: "warn"}


class LogPanel(QWidget):
    """進捗バー・ステータス表示・ログ表示・実行ボタン群を持つ共通の下部パネル。"""

    def __init__(self, run_label: str, on_run, show_open_result: bool = True, parent=None):
        super().__init__(parent)
        self.on_run = on_run
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.progress = ProgressTracker()
        self.result_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.run_button = QPushButton(run_label)
        self.run_button.clicked.connect(lambda: self.on_run())
        btn_row.addWidget(self.run_button)

        self.open_result_button = QPushButton("結果Excelを開く")
        self.open_result_button.setObjectName("secondaryButton")
        self.open_result_button.setEnabled(False)
        self.open_result_button.clicked.connect(self._open_result)
        if show_open_result:
            btn_row.addWidget(self.open_result_button)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        layout.addWidget(self.progress_bar)

        self.log_widget = QPlainTextEdit()
        self.log_widget.setReadOnly(True)
        layout.addWidget(self.log_widget, stretch=1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_queue)
        self._timer.start(100)

    def stop(self) -> None:
        self._timer.stop()

    def start(self, worker) -> None:
        self.log_widget.clear()
        self.progress.reset()
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.open_result_button.setEnabled(False)
        self.result_path = None
        self._set_status("実行中...", "running")
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, code: int, result_path: Path | None) -> None:
        self.log_queue.put(("final", code, result_path))

    def _set_status(self, text: str, state: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item[0] == "line":
                    line = item[1]
                    self.log_widget.appendPlainText(line)
                    self.progress.feed_line(line)
                    self.progress_bar.setValue(self.progress.percent)
                elif item[0] == "final":
                    code, result_path = item[1], item[2]
                    self._set_status(exit_code_meaning(code), STATE_BY_CODE.get(code, "ng"))
                    self.run_button.setEnabled(True)
                    self.result_path = result_path
                    if result_path and Path(result_path).exists():
                        self.open_result_button.setEnabled(True)
                    if code == 0:
                        self.progress_bar.setValue(100)
        except queue.Empty:
            pass

    def _open_result(self) -> None:
        if self.result_path and self.result_path.exists():
            os.startfile(str(self.result_path))  # noqa: S606 - Windows専用ツールのため


class GenerateRunTab(QWidget):
    """openapi-test-gen で生成 → openapi-test-run で実行、を1クリックで行うタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)

        self.openapi_field = PathField("openapi.json", name_filter=JSON_FILTER)
        self.openapi_field.set(settings["gen_openapi_path"])
        layout.addWidget(self.openapi_field)

        self.output_dir_field = PathField("出力先フォルダ", is_dir=True)
        self.output_dir_field.set(settings["gen_output_dir"])
        layout.addWidget(self.output_dir_field)

        self.base_url_field = TextField("Base URL", settings["gen_base_url"])
        layout.addWidget(self.base_url_field)

        self.health_path_field = TextField("Health Path", settings["gen_health_path"])
        layout.addWidget(self.health_path_field)

        self.auth_config_field = PathField("認証設定(任意)", name_filter=JSON_FILTER)
        self.auth_config_field.set(settings["gen_auth_config_path"])
        layout.addWidget(self.auth_config_field)

        self.dry_run_checkbox = QCheckBox("dry-run（実際にはリクエストを送信しない。生成内容の確認用）")
        self.dry_run_checkbox.setChecked(bool(settings["gen_dry_run"]))
        layout.addWidget(self.dry_run_checkbox)

        self.panel = LogPanel("生成して実行", self.on_run)
        layout.addWidget(self.panel, stretch=1)

    def save_fields(self) -> None:
        self.settings["gen_openapi_path"] = self.openapi_field.get()
        self.settings["gen_output_dir"] = self.output_dir_field.get()
        self.settings["gen_base_url"] = self.base_url_field.get()
        self.settings["gen_health_path"] = self.health_path_field.get()
        self.settings["gen_auth_config_path"] = self.auth_config_field.get()
        self.settings["gen_dry_run"] = self.dry_run_checkbox.isChecked()

    def on_run(self) -> None:
        openapi_path = self.openapi_field.get()
        base_url = self.base_url_field.get()
        if not openapi_path:
            QMessageBox.critical(self, "入力エラー", "openapi.json を選択してください")
            return
        if not base_url:
            QMessageBox.critical(self, "入力エラー", "Base URL を入力してください")
            return

        output_dir = Path(self.output_dir_field.get() or Path(openapi_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_path = output_dir / "試験仕様.xlsx"
        cases_path = output_dir / "test_cases.json"
        result_path = output_dir / "試験仕様_result.xlsx"
        health_path = self.health_path_field.get() or "/health"
        auth_config_path = self.auth_config_field.get()
        dry_run = self.dry_run_checkbox.isChecked()

        self.save_fields()

        def worker() -> None:
            gen_cmd = [
                sys.executable, "-u", str(CLI_PY), openapi_path,
                "-o", str(cases_path), "--excel-output", str(spec_path),
            ]
            code = run_streamed(gen_cmd, self.panel.log_queue)
            if code != 0:
                self.panel.log_queue.put(("line", f"[ERROR] テスト仕様の生成に失敗しました（終了コード {code}）"))
                self.panel.finish(code, None)
                return

            self.panel.log_queue.put(("line", ""))
            run_cmd = [
                sys.executable, "-u", str(RUNNER_PY), str(spec_path), openapi_path,
                "--base-url", base_url, "--health-path", health_path,
                "--output", str(result_path),
            ]
            if auth_config_path:
                run_cmd += ["--auth-config", auth_config_path]
            if dry_run:
                run_cmd += ["--dry-run"]
            code = run_streamed(run_cmd, self.panel.log_queue)
            self.panel.finish(code, result_path)

        self.panel.start(worker)


class DBScenarioTab(QWidget):
    """db_scenario_runner.py を実行するタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)

        self.scenario_field = PathField("シナリオYAML", name_filter=YAML_FILTER)
        self.scenario_field.set(settings["db_scenario_path"])
        layout.addWidget(self.scenario_field)

        self.openapi_field = PathField("openapi.json", name_filter=JSON_FILTER)
        self.openapi_field.set(settings["db_openapi_path"])
        layout.addWidget(self.openapi_field)

        self.config_field = PathField("config.json", name_filter=JSON_FILTER)
        self.config_field.set(settings["db_config_path"])
        layout.addWidget(self.config_field)

        self.base_url_field = TextField("Base URL", settings["db_base_url"])
        layout.addWidget(self.base_url_field)

        self.health_path_field = TextField("Health Path", settings["db_health_path"])
        layout.addWidget(self.health_path_field)

        self.auth_config_field = PathField("認証設定(任意)", name_filter=JSON_FILTER)
        self.auth_config_field.set(settings["db_auth_config_path"])
        layout.addWidget(self.auth_config_field)

        self.dry_run_checkbox = QCheckBox("dry-run（実際にはAPIリクエスト送信・DB接続を行わない。設定内容の確認用）")
        self.dry_run_checkbox.setChecked(bool(settings["db_dry_run"]))
        layout.addWidget(self.dry_run_checkbox)

        self.panel = LogPanel("実行", self.on_run, show_open_result=False)
        layout.addWidget(self.panel, stretch=1)

    def save_fields(self) -> None:
        self.settings["db_scenario_path"] = self.scenario_field.get()
        self.settings["db_openapi_path"] = self.openapi_field.get()
        self.settings["db_config_path"] = self.config_field.get()
        self.settings["db_base_url"] = self.base_url_field.get()
        self.settings["db_health_path"] = self.health_path_field.get()
        self.settings["db_auth_config_path"] = self.auth_config_field.get()
        self.settings["db_dry_run"] = self.dry_run_checkbox.isChecked()

    def on_run(self) -> None:
        scenario_path = self.scenario_field.get()
        openapi_path = self.openapi_field.get()
        config_path = self.config_field.get()
        base_url = self.base_url_field.get()
        if not scenario_path or not openapi_path or not config_path:
            QMessageBox.critical(self, "入力エラー", "シナリオYAML・openapi.json・config.json をすべて選択してください")
            return
        if not base_url:
            QMessageBox.critical(self, "入力エラー", "Base URL を入力してください")
            return

        health_path = self.health_path_field.get() or "/health"
        auth_config_path = self.auth_config_field.get()
        dry_run = self.dry_run_checkbox.isChecked()
        self.save_fields()

        def worker() -> None:
            cmd = [
                sys.executable, "-u", str(DB_SCENARIO_RUNNER_PY), scenario_path, openapi_path,
                "--base-url", base_url, "--config", config_path, "--health-path", health_path,
            ]
            if auth_config_path:
                cmd += ["--auth-config", auth_config_path]
            if dry_run:
                cmd += ["--dry-run"]
            code = run_streamed(cmd, self.panel.log_queue)
            self.panel.finish(code, None)

        self.panel.start(worker)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("openapi-test-gen / openapi-test-run")
        self.resize(960, 720)

        self.settings = load_settings()

        tabs = QTabWidget()
        self.gen_tab = GenerateRunTab(self.settings)
        self.db_tab = DBScenarioTab(self.settings)
        tabs.addTab(self.gen_tab, "テスト生成・実行")
        tabs.addTab(self.db_tab, "DBシナリオ")

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(tabs)
        self.setCentralWidget(container)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qtのオーバーライド規約
        self.gen_tab.save_fields()
        self.db_tab.save_fields()
        save_settings(self.settings)
        self.gen_tab.panel.stop()
        self.db_tab.panel.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    qss_path = Path(__file__).resolve().parent / "style.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
