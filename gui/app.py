#!/usr/bin/env python3
"""openapi-test-gen / openapi-test-run / db_scenario_runner をGUIから操作するデスクトップアプリ（PySide6版）。

既存のCLIツール群をそのままサブプロセスとして呼び出す薄いラッパー。
CLI自体はこれまで通り単独でも使用できる。
"""
from __future__ import annotations
import json
import os
import queue
import sys
import threading
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QPushButton, QLabel, QProgressBar, QPlainTextEdit, QMessageBox, QCheckBox, QComboBox,
)

from settings import load_settings, save_settings
from widgets import PathField, TextField
from process_runner import run_streamed, exit_code_meaning
from progress_parser import ProgressTracker
import validators
from highlighters import YamlConfidenceHighlighter, SqlHighlighter

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PY = REPO_ROOT / "src" / "cli.py"
RUNNER_PY = REPO_ROOT / "runner" / "runner.py"
DB_SCENARIO_RUNNER_PY = REPO_ROOT / "runner" / "db_scenario_runner.py"
GENERATE_MAPPING_PY = REPO_ROOT / "runner" / "generate_mapping.py"
GENERATE_SETUP_SQL_PY = REPO_ROOT / "runner" / "generate_setup_sql.py"
GENERATE_DB_SCENARIOS_PY = REPO_ROOT / "runner" / "generate_db_scenarios.py"

_GENERATOR_EXIT_MEANINGS = {0: "OK：生成完了", 1: "ERROR：生成に失敗しました"}

JSON_FILTER = "JSON (*.json)"
YAML_FILTER = "YAML (*.yaml *.yml)"
SQL_FILTER = "SQL (*.sql)"

STATE_BY_CODE = {0: "ok", 1: "ng", 2: "warn"}


def _confirm_overwrite(parent, paths: list[Path]) -> bool:
    """既に存在するファイルがあれば上書き確認を出す。存在しなければ確認なしでTrue。"""
    existing = [p for p in paths if p.exists()]
    if not existing:
        return True
    names = "\n".join(f"・{p.name}" for p in existing)
    reply = QMessageBox.question(
        parent, "上書き確認",
        f"以下のファイルは既に存在します。上書きしてよろしいですか？\n{names}",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes


def _show_validation(parent, title: str, checks: list[tuple[str, str]]) -> None:
    """checks: [(表示名, 検証結果文字列), ...] をダイアログで表示する。"""
    text = "\n".join(f"{label}: {result}" for label, result in checks)
    QMessageBox.information(parent, title, text)


class LogPanel(QWidget):
    """進捗バー・ステータス表示・ログ表示・実行ボタン群を持つ共通の下部パネル。"""

    def __init__(
        self, run_label: str, on_run, show_open_result: bool = True,
        open_result_label: str = "結果Excelを開く", exit_code_meanings: dict[int, str] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.on_run = on_run
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()
        self.progress = ProgressTracker()
        self.result_path: Path | None = None
        self.exit_code_meanings = exit_code_meanings
        # 完了時(mainスレッド上、_poll_queue経由)に呼ばれる任意のフック。
        # 生成結果のプレビュー表示や、他タブへのパス連携に使う。
        self.on_finish = None
        # 実行中のサブプロセス（キャンセル/GUI終了時に強制終了するため保持する）。
        # run_streamed()のon_startコールバック経由でバックグラウンドスレッドから設定される。
        self.current_process = None
        self._cancelled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.run_button = QPushButton(run_label)
        self.run_button.clicked.connect(lambda: self.on_run())
        btn_row.addWidget(self.run_button)

        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel)
        btn_row.addWidget(self.cancel_button)

        self.open_result_button = QPushButton(open_result_label)
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
        self.cancel()  # GUI終了時にも実行中のサブプロセスを残さないよう終了させる

    def start(self, worker) -> None:
        self.log_widget.clear()
        self.progress.reset()
        self.progress_bar.setValue(0)
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.open_result_button.setEnabled(False)
        self.result_path = None
        self.current_process = None
        self._cancelled = False
        self._set_status("実行中...", "running")
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, code: int, result_path: Path | None) -> None:
        self.log_queue.put(("final", code, result_path))

    def is_running(self) -> bool:
        return self.current_process is not None and self.current_process.poll() is None

    def register_process(self, proc) -> None:
        """run_streamed()のon_startから呼ばれる。バックグラウンドスレッド側から実行される想定。"""
        self.current_process = proc

    def cancel(self) -> None:
        if self.is_running():
            self._cancelled = True
            try:
                self.current_process.terminate()
            except OSError:
                pass

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
                    if self._cancelled:
                        meaning, state = "キャンセルしました", "warn"
                    else:
                        meaning = (
                            self.exit_code_meanings.get(code, f"終了コード {code}")
                            if self.exit_code_meanings is not None
                            else exit_code_meaning(code)
                        )
                        state = STATE_BY_CODE.get(code, "ng")
                    self._set_status(meaning, state)
                    self.run_button.setEnabled(True)
                    self.cancel_button.setEnabled(False)
                    self.current_process = None
                    self.result_path = result_path
                    if result_path and Path(result_path).exists():
                        self.open_result_button.setEnabled(True)
                    if code == 0:
                        self.progress_bar.setValue(100)
                    if self.on_finish:
                        self.on_finish(code, result_path)
        except queue.Empty:
            pass

    def _open_result(self) -> None:
        if self.result_path and self.result_path.exists():
            os.startfile(str(self.result_path))  # noqa: S606 - Windows専用ツールのため


class ConnectivityCheckRow(QWidget):
    """DB接続設定(config.json)が実際にPostgreSQL/InfluxDBへ接続できるかを確認するボタン+ステータス表示。

    validators.validate_db_config はファイルの形式（必須キーの有無）しか見ないため、
    「形式は正しいが実際には繋がらない」場合を検知できない。ここではネットワーク越しに
    実接続を試みる。ハングする可能性があるため、必ずバックグラウンドスレッドで実行し、
    UIをブロックしない。
    """

    def __init__(self, get_config_path, parent=None):
        super().__init__(parent)
        self.get_config_path = get_config_path
        self._queue: "queue.Queue[str]" = queue.Queue()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.check_button = QPushButton("DB接続を確認")
        self.check_button.setObjectName("secondaryButton")
        self.check_button.clicked.connect(self.on_check)
        layout.addWidget(self.check_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, stretch=1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(150)

    def stop(self) -> None:
        self._timer.stop()

    def on_check(self) -> None:
        path = self.get_config_path()
        if not path:
            self.status_label.setText("DB接続設定が未入力です")
            return
        self.check_button.setEnabled(False)
        self.status_label.setText("確認中...")

        def worker() -> None:
            result = validators.check_db_connectivity(path)
            self._queue.put(result)

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                result = self._queue.get_nowait()
                self.status_label.setText(result)
                self.check_button.setEnabled(True)
        except queue.Empty:
            pass


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

        health_note = QLabel(
            "対象APIの疎通確認に使うパスです。ここが200番台を返さないと試験は1件も実行されず、"
            "「ヘルスチェック失敗」で即座に中断します。対象APIに/healthが無い場合は、GETで200番台が"
            "返る既存のパス（例: /、または対象APIの一覧取得系エンドポイントなど）に変更してください。"
        )
        health_note.setWordWrap(True)
        layout.addWidget(health_note)

        self.auth_config_field = PathField("認証設定(任意)", name_filter=JSON_FILTER)
        self.auth_config_field.set(settings["gen_auth_config_path"])
        layout.addWidget(self.auth_config_field)

        self.config_field = PathField("DB接続設定(任意)", name_filter=JSON_FILTER)
        self.config_field.set(settings["gen_config_path"])
        layout.addWidget(self.config_field)

        self.setup_field = PathField("setup SQL(任意)", name_filter=SQL_FILTER)
        self.setup_field.set(settings["gen_setup_path"])
        layout.addWidget(self.setup_field)

        self.teardown_field = PathField("teardown SQL(任意)", name_filter=SQL_FILTER)
        self.teardown_field.set(settings["gen_teardown_path"])
        layout.addWidget(self.teardown_field)

        self.dry_run_checkbox = QCheckBox("dry-run（実際にはリクエストを送信しない。生成内容の確認用）")
        self.dry_run_checkbox.setChecked(bool(settings["gen_dry_run"]))
        layout.addWidget(self.dry_run_checkbox)

        self.full_body_checkbox = QCheckBox("full-body（結果Excelの実測ボディを省略せず全文出力する）")
        self.full_body_checkbox.setChecked(bool(settings["gen_full_body"]))
        layout.addWidget(self.full_body_checkbox)

        self.fail_fast_checkbox = QCheckBox("fail-fast（最初のNGが出た時点で試験を打ち切る）")
        self.fail_fast_checkbox.setChecked(bool(settings["gen_fail_fast"]))
        layout.addWidget(self.fail_fast_checkbox)

        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("入力を確認")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate)
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        layout.addLayout(validate_row)

        self.connectivity_row = ConnectivityCheckRow(self.config_field.get)
        layout.addWidget(self.connectivity_row)

        self.panel = LogPanel("生成して実行", self.on_run)
        layout.addWidget(self.panel, stretch=1)

    def on_validate(self) -> None:
        _show_validation(self, "入力の確認結果", [
            ("openapi.json", validators.validate_openapi(self.openapi_field.get())),
            ("認証設定", validators.validate_auth_config(self.auth_config_field.get())),
            ("DB接続設定", validators.validate_db_config(self.config_field.get(), required=False)),
            ("setup SQL", validators.validate_sql_file(self.setup_field.get())),
            ("teardown SQL", validators.validate_sql_file(self.teardown_field.get())),
        ])

    def save_fields(self) -> None:
        self.settings["gen_openapi_path"] = self.openapi_field.get()
        self.settings["gen_output_dir"] = self.output_dir_field.get()
        self.settings["gen_base_url"] = self.base_url_field.get()
        self.settings["gen_health_path"] = self.health_path_field.get()
        self.settings["gen_auth_config_path"] = self.auth_config_field.get()
        self.settings["gen_dry_run"] = self.dry_run_checkbox.isChecked()
        self.settings["gen_config_path"] = self.config_field.get()
        self.settings["gen_setup_path"] = self.setup_field.get()
        self.settings["gen_teardown_path"] = self.teardown_field.get()
        self.settings["gen_full_body"] = self.full_body_checkbox.isChecked()
        self.settings["gen_fail_fast"] = self.fail_fast_checkbox.isChecked()

    def _confirm_setup_teardown(self) -> bool:
        """setup/teardown SQLはロールバックされず実DBに即反映されるため、実行前に必ず確認する。

        「DB準備」タブで生成したSQLのパスが自動連携でここに入っていることがあり、
        本人が意識しないまま実DBへ反映されてしまう事故を防ぐための確認。
        """
        reply = QMessageBox.warning(
            self, "setup/teardown SQLの実行確認",
            "setup SQL / teardown SQL が指定されています。「生成して実行」を行うと、これらのSQLは"
            "実行前後に実際のDBへ即座に反映されます（ロールバックされません）。"
            "「DB準備」タブで生成したファイルが自動で入っている場合もあるため、内容をよく確認してから"
            "続行してください。本当に実行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def on_run(self) -> None:
        openapi_path = self.openapi_field.get()
        base_url = self.base_url_field.get()
        if not openapi_path:
            QMessageBox.critical(self, "入力エラー", "openapi.json を選択してください")
            return
        if not base_url:
            QMessageBox.critical(self, "入力エラー", "Base URL を入力してください")
            return

        config_path = self.config_field.get()
        setup_path = self.setup_field.get()
        teardown_path = self.teardown_field.get()
        if (setup_path or teardown_path) and not config_path:
            QMessageBox.critical(
                self, "入力エラー", "setup SQL または teardown SQL を指定する場合は DB接続設定 が必要です"
            )
            return
        if (setup_path or teardown_path) and not self._confirm_setup_teardown():
            return

        output_dir = Path(self.output_dir_field.get() or Path(openapi_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_path = output_dir / "試験仕様.xlsx"
        cases_path = output_dir / "test_cases.json"
        result_path = output_dir / "試験仕様_result.xlsx"
        health_path = self.health_path_field.get() or "/health"
        auth_config_path = self.auth_config_field.get()
        dry_run = self.dry_run_checkbox.isChecked()
        full_body = self.full_body_checkbox.isChecked()
        fail_fast = self.fail_fast_checkbox.isChecked()

        self.save_fields()

        def worker() -> None:
            gen_cmd = [
                sys.executable, "-u", str(CLI_PY), openapi_path,
                "-o", str(cases_path), "--excel-output", str(spec_path),
            ]
            code = run_streamed(gen_cmd, self.panel.log_queue, on_start=self.panel.register_process)
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
            if config_path:
                run_cmd += ["--config", config_path]
            if setup_path:
                run_cmd += ["--setup", setup_path]
            if teardown_path:
                run_cmd += ["--teardown", teardown_path]
            if full_body:
                run_cmd += ["--full-body"]
            if fail_fast:
                run_cmd += ["--fail-fast"]
            if dry_run:
                run_cmd += ["--dry-run"]
            code = run_streamed(run_cmd, self.panel.log_queue, on_start=self.panel.register_process)
            self.panel.finish(code, result_path)

        self.panel.start(worker)


class ConfigBuilderTab(QWidget):
    """config.json（DB接続設定）をGUIのフォームから作成・編集するタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        # 保存成功時に呼ばれる任意のフック（他タブへのパス連携用）。MainWindowが設定する。
        self.on_saved = None

        layout = QVBoxLayout(self)

        self.output_path_field = PathField("保存先", name_filter=JSON_FILTER, for_saving=True)
        self.output_path_field.set(settings["cfg_output_path"])
        layout.addWidget(self.output_path_field)

        io_row = QHBoxLayout()
        self.load_button = QPushButton("読み込む")
        self.load_button.setObjectName("secondaryButton")
        self.load_button.clicked.connect(self.on_load)
        io_row.addWidget(self.load_button)
        io_row.addStretch(1)
        layout.addLayout(io_row)

        self.pg_checkbox = QCheckBox("PostgreSQLを使う")
        self.pg_checkbox.setChecked(bool(settings["cfg_pg_enabled"]))
        layout.addWidget(self.pg_checkbox)

        self.pg_host = TextField("　host", settings["cfg_pg_host"])
        layout.addWidget(self.pg_host)
        self.pg_port = TextField("　port", settings["cfg_pg_port"])
        layout.addWidget(self.pg_port)
        self.pg_dbname = TextField("　dbname", settings["cfg_pg_dbname"])
        layout.addWidget(self.pg_dbname)
        self.pg_user = TextField("　user", settings["cfg_pg_user"])
        layout.addWidget(self.pg_user)
        self.pg_password = TextField("　password", "")  # パスワードは保存しない
        layout.addWidget(self.pg_password)

        self.influx_checkbox = QCheckBox("InfluxDBを使う")
        self.influx_checkbox.setChecked(bool(settings["cfg_influx_enabled"]))
        layout.addWidget(self.influx_checkbox)

        self.influx_host = TextField("　host", settings["cfg_influx_host"])
        layout.addWidget(self.influx_host)
        self.influx_port = TextField("　port", settings["cfg_influx_port"])
        layout.addWidget(self.influx_port)
        self.influx_database = TextField("　database", settings["cfg_influx_database"])
        layout.addWidget(self.influx_database)
        self.influx_username = TextField("　username(任意)", settings["cfg_influx_username"])
        layout.addWidget(self.influx_username)
        self.influx_password = TextField("　password(任意)", "")  # パスワードは保存しない
        layout.addWidget(self.influx_password)

        save_row = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.on_save)
        save_row.addWidget(self.save_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.connectivity_row = ConnectivityCheckRow(self.output_path_field.get)
        layout.addWidget(self.connectivity_row)

        layout.addStretch(1)

    def save_fields(self) -> None:
        self.settings["cfg_output_path"] = self.output_path_field.get()
        self.settings["cfg_pg_enabled"] = self.pg_checkbox.isChecked()
        self.settings["cfg_pg_host"] = self.pg_host.get()
        self.settings["cfg_pg_port"] = self.pg_port.get()
        self.settings["cfg_pg_dbname"] = self.pg_dbname.get()
        self.settings["cfg_pg_user"] = self.pg_user.get()
        self.settings["cfg_influx_enabled"] = self.influx_checkbox.isChecked()
        self.settings["cfg_influx_host"] = self.influx_host.get()
        self.settings["cfg_influx_port"] = self.influx_port.get()
        self.settings["cfg_influx_database"] = self.influx_database.get()
        self.settings["cfg_influx_username"] = self.influx_username.get()
        # パスワードは意図的に保存しない（設定ファイルへの平文保存を避けるため）

    @staticmethod
    def _parse_port(text: str, field_label: str) -> int:
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"{field_label} のポート番号は数値で入力してください: {text!r}")

    def _collect_config(self) -> dict:
        data: dict = {}
        if self.pg_checkbox.isChecked():
            data["postgres"] = {
                "host": self.pg_host.get(),
                "port": self._parse_port(self.pg_port.get(), "PostgreSQL"),
                "dbname": self.pg_dbname.get(),
                "user": self.pg_user.get(),
                "password": self.pg_password.get(),
            }
        if self.influx_checkbox.isChecked():
            influx: dict = {
                "host": self.influx_host.get(),
                "port": self._parse_port(self.influx_port.get(), "InfluxDB"),
                "database": self.influx_database.get(),
            }
            if self.influx_username.get():
                influx["username"] = self.influx_username.get()
            if self.influx_password.get():
                influx["password"] = self.influx_password.get()
            data["influxdb"] = influx
        return data

    def on_save(self) -> None:
        output_path = self.output_path_field.get()
        if not output_path:
            QMessageBox.critical(self, "入力エラー", "保存先を指定してください")
            return
        if not self.pg_checkbox.isChecked() and not self.influx_checkbox.isChecked():
            QMessageBox.critical(self, "入力エラー", "PostgreSQL/InfluxDBのいずれかは有効にしてください")
            return
        try:
            data = self._collect_config()
        except ValueError as e:
            QMessageBox.critical(self, "入力エラー", str(e))
            return

        self.save_fields()
        Path(output_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        result = validators.validate_db_config(output_path)
        self.status_label.setText(f"保存しました: {output_path}\n{result}")
        if self.on_saved:
            self.on_saved(Path(output_path))

    def on_load(self) -> None:
        path = self.output_path_field.get()
        if not path or not Path(path).exists():
            QMessageBox.critical(self, "入力エラー", "読み込むファイルが見つかりません")
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "読み込みエラー", f"JSONの解析に失敗しました: {e}")
            return

        pg = data.get("postgres")
        self.pg_checkbox.setChecked(bool(pg))
        if isinstance(pg, dict):
            self.pg_host.set(str(pg.get("host", "")))
            self.pg_port.set(str(pg.get("port", "")))
            self.pg_dbname.set(str(pg.get("dbname", "")))
            self.pg_user.set(str(pg.get("user", "")))
            self.pg_password.set(str(pg.get("password", "")))

        influx = data.get("influxdb")
        self.influx_checkbox.setChecked(bool(influx))
        if isinstance(influx, dict):
            self.influx_host.set(str(influx.get("host", "")))
            self.influx_port.set(str(influx.get("port", "")))
            self.influx_database.set(str(influx.get("database", "")))
            self.influx_username.set(str(influx.get("username", "")))
            self.influx_password.set(str(influx.get("password", "")))

        self.status_label.setText(f"読み込みました: {path}")


class AuthConfigBuilderTab(QWidget):
    """auth_config.yaml（ログイン認証設定）をGUIのフォームから作成・編集するタブ。"""

    _METHODS = ["POST", "GET", "PUT", "PATCH"]

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        # 保存成功時に呼ばれる任意のフック（他タブへのパス連携用）。MainWindowが設定する。
        self.on_saved = None

        layout = QVBoxLayout(self)

        self.output_path_field = PathField("保存先", name_filter=YAML_FILTER, for_saving=True)
        self.output_path_field.set(settings["authb_output_path"])
        layout.addWidget(self.output_path_field)

        io_row = QHBoxLayout()
        self.load_button = QPushButton("読み込む")
        self.load_button.setObjectName("secondaryButton")
        self.load_button.clicked.connect(self.on_load)
        io_row.addWidget(self.load_button)
        io_row.addStretch(1)
        layout.addLayout(io_row)

        self.login_url_field = TextField("login_url", settings["authb_login_url"])
        layout.addWidget(self.login_url_field)

        method_row = QHBoxLayout()
        method_label = QLabel("method")
        method_label.setFixedWidth(120)
        method_row.addWidget(method_label)
        self.method_combo = QComboBox()
        self.method_combo.addItems(self._METHODS)
        idx = self.method_combo.findText(settings["authb_method"])
        self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)
        method_row.addWidget(self.method_combo, stretch=1)
        layout.addLayout(method_row)

        body_label = QLabel("body（任意, JSON形式）")
        layout.addWidget(body_label)
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlainText(settings["authb_body"])
        self.body_edit.setFixedHeight(80)
        layout.addWidget(self.body_edit)

        self.token_path_field = TextField("token_path", settings["authb_token_path"])
        layout.addWidget(self.token_path_field)

        self.header_name_field = TextField("header_name", settings["authb_header_name"])
        layout.addWidget(self.header_name_field)

        self.header_format_field = TextField("header_format", settings["authb_header_format"])
        layout.addWidget(self.header_format_field)

        save_row = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.on_save)
        save_row.addWidget(self.save_button)
        save_row.addStretch(1)
        layout.addLayout(save_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    def save_fields(self) -> None:
        self.settings["authb_output_path"] = self.output_path_field.get()
        self.settings["authb_login_url"] = self.login_url_field.get()
        self.settings["authb_method"] = self.method_combo.currentText()
        self.settings["authb_body"] = self.body_edit.toPlainText()
        self.settings["authb_token_path"] = self.token_path_field.get()
        self.settings["authb_header_name"] = self.header_name_field.get()
        self.settings["authb_header_format"] = self.header_format_field.get()

    def on_save(self) -> None:
        output_path = self.output_path_field.get()
        login_url = self.login_url_field.get()
        if not output_path or not login_url:
            QMessageBox.critical(self, "入力エラー", "保存先と login_url を入力してください")
            return

        body_text = self.body_edit.toPlainText().strip()
        body = None
        if body_text:
            try:
                body = json.loads(body_text)
            except json.JSONDecodeError as e:
                QMessageBox.critical(self, "入力エラー", f"body のJSON解析に失敗しました: {e}")
                return

        data: dict = {"login_url": login_url, "method": self.method_combo.currentText()}
        if body is not None:
            data["body"] = body
        data["token_path"] = self.token_path_field.get() or "access_token"
        data["header_name"] = self.header_name_field.get() or "Authorization"
        data["header_format"] = self.header_format_field.get() or "Bearer {token}"

        self.save_fields()
        Path(output_path).write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        result = validators.validate_auth_config(output_path)
        self.status_label.setText(f"保存しました: {output_path}\n{result}")
        if self.on_saved:
            self.on_saved(Path(output_path))

    def on_load(self) -> None:
        path = self.output_path_field.get()
        if not path or not Path(path).exists():
            QMessageBox.critical(self, "入力エラー", "読み込むファイルが見つかりません")
            return

        from auth_login import load_auth_config, AuthLoginError

        try:
            data = load_auth_config(path)
        except AuthLoginError as e:
            QMessageBox.critical(self, "読み込みエラー", str(e))
            return

        self.login_url_field.set(str(data.get("login_url", "")))
        idx = self.method_combo.findText(str(data.get("method", "POST")).upper())
        self.method_combo.setCurrentIndex(idx if idx >= 0 else 0)
        body = data.get("body")
        self.body_edit.setPlainText(json.dumps(body, ensure_ascii=False, indent=2) if body else "")
        self.token_path_field.set(str(data.get("token_path", "access_token")))
        self.header_name_field.set(str(data.get("header_name", "Authorization")))
        self.header_format_field.set(str(data.get("header_format", "Bearer {token}")))

        self.status_label.setText(f"読み込みました: {path}")


class MappingGenTab(QWidget):
    """generate_mapping.py（mapping.yaml叩き台生成）を実行するタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)

        self.openapi_field = PathField("openapi.json", name_filter=JSON_FILTER)
        self.openapi_field.set(settings["mapgen_openapi_path"])
        layout.addWidget(self.openapi_field)

        self.config_field = PathField("DB接続設定", name_filter=JSON_FILTER)
        self.config_field.set(settings["mapgen_config_path"])
        layout.addWidget(self.config_field)

        self.schema_field = TextField("対象スキーマ", settings["mapgen_schema"])
        layout.addWidget(self.schema_field)

        self.output_dir_field = PathField("出力先フォルダ", is_dir=True)
        self.output_dir_field.set(settings["mapgen_output_dir"])
        layout.addWidget(self.output_dir_field)

        note = QLabel(
            "実DBに接続し、operationIdごとにテーブル名の候補を推定してmapping.yaml.generatedを"
            "出力します。確信度（高/中/低）を必ず確認し、特に「低」は手動で修正してください。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("入力を確認")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate)
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        layout.addLayout(validate_row)

        self.connectivity_row = ConnectivityCheckRow(self.config_field.get)
        layout.addWidget(self.connectivity_row)

        self.panel = LogPanel(
            "mapping.yaml生成", self.on_run,
            open_result_label="生成結果を開く", exit_code_meanings=_GENERATOR_EXIT_MEANINGS,
        )
        layout.addWidget(self.panel, stretch=1)

        preview_label = QLabel("生成結果プレビュー（確信度コメントを確認しながら、その場で編集・保存できます）")
        layout.addWidget(preview_label)
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setFixedHeight(160)
        self._preview_highlighter = YamlConfidenceHighlighter(self.preview_edit.document())
        layout.addWidget(self.preview_edit)

        preview_btn_row = QHBoxLayout()
        self.save_preview_button = QPushButton("保存")
        self.save_preview_button.setObjectName("secondaryButton")
        self.save_preview_button.setEnabled(False)
        self.save_preview_button.clicked.connect(self.on_save_preview)
        preview_btn_row.addWidget(self.save_preview_button)
        preview_btn_row.addStretch(1)
        layout.addLayout(preview_btn_row)

        self.preview_status_label = QLabel("")
        self.preview_status_label.setWordWrap(True)
        layout.addWidget(self.preview_status_label)

        self._current_output_path: "Path | None" = None
        self._preview_validate_timer = QTimer(self)
        self._preview_validate_timer.setSingleShot(True)
        self._preview_validate_timer.timeout.connect(self._validate_preview)
        self.preview_edit.textChanged.connect(lambda: self._preview_validate_timer.start(500))

        self.panel.on_finish = self._on_generated

    def _on_generated(self, code: int, path: "Path | None") -> None:
        if code == 0 and path and Path(path).exists():
            self._current_output_path = Path(path)
            self.preview_edit.setPlainText(Path(path).read_text(encoding="utf-8"))
            self.save_preview_button.setEnabled(True)
        else:
            self._current_output_path = None
            self.preview_edit.clear()
            self.save_preview_button.setEnabled(False)

    def _validate_preview(self) -> None:
        self.preview_status_label.setText(validators.validate_mapping_yaml_text(self.preview_edit.toPlainText()))

    def on_save_preview(self) -> None:
        if not self._current_output_path:
            return
        self._current_output_path.write_text(self.preview_edit.toPlainText(), encoding="utf-8")
        self.preview_status_label.setText(f"保存しました: {self._current_output_path}")

    def on_validate(self) -> None:
        _show_validation(self, "入力の確認結果", [
            ("openapi.json", validators.validate_openapi(self.openapi_field.get())),
            ("DB接続設定", validators.validate_db_config(self.config_field.get())),
        ])

    def save_fields(self) -> None:
        self.settings["mapgen_openapi_path"] = self.openapi_field.get()
        self.settings["mapgen_config_path"] = self.config_field.get()
        self.settings["mapgen_schema"] = self.schema_field.get()
        self.settings["mapgen_output_dir"] = self.output_dir_field.get()

    def on_run(self) -> None:
        openapi_path = self.openapi_field.get()
        config_path = self.config_field.get()
        if not openapi_path or not config_path:
            QMessageBox.critical(self, "入力エラー", "openapi.json と DB接続設定 を選択してください")
            return

        output_dir = Path(self.output_dir_field.get() or Path(openapi_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "mapping.yaml.generated"
        schema = self.schema_field.get()

        if not _confirm_overwrite(self, [output_path]):
            return

        self.save_fields()

        def worker() -> None:
            cmd = [
                sys.executable, "-u", str(GENERATE_MAPPING_PY), openapi_path,
                "--config", config_path, "-o", str(output_path),
            ]
            if schema:
                cmd += ["--schema", schema]
            code = run_streamed(cmd, self.panel.log_queue, on_start=self.panel.register_process)
            self.panel.finish(code, output_path if code == 0 else None)

        self.panel.start(worker)


class SetupSqlGenTab(QWidget):
    """generate_setup_sql.py（setup.sql/teardown.sql雛形生成）を実行するタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)

        self.config_field = PathField("DB接続設定", name_filter=JSON_FILTER)
        self.config_field.set(settings["sqlgen_config_path"])
        layout.addWidget(self.config_field)

        self.schema_field = TextField("対象スキーマ", settings["sqlgen_schema"])
        layout.addWidget(self.schema_field)

        self.tables_field = TextField("対象テーブル(任意, カンマ区切り)", settings["sqlgen_tables"])
        layout.addWidget(self.tables_field)

        self.output_dir_field = PathField("出力先フォルダ", is_dir=True)
        self.output_dir_field.set(settings["sqlgen_output_dir"])
        layout.addWidget(self.output_dir_field)

        note = QLabel(
            "実DBのスキーマから、外部キー順序を満たすsetup.sql.generated / teardown.sql.generated を"
            "出力します。値の中身（実際に意味のあるテストデータかどうか）は必ず確認してください。\n"
            "※ここで生成・保存しただけではDBには何も反映されません。プレビュー下部の"
            "「setup.sqlを実行（DBに反映）」を別途押すまで、実DBへのデータ投入は行われません。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("入力を確認")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate)
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        layout.addLayout(validate_row)

        self.connectivity_row = ConnectivityCheckRow(self.config_field.get)
        layout.addWidget(self.connectivity_row)

        self.panel = LogPanel(
            "setup.sql/teardown.sql生成", self.on_run,
            open_result_label="生成結果を開く", exit_code_meanings=_GENERATOR_EXIT_MEANINGS,
        )
        layout.addWidget(self.panel, stretch=1)

        preview_label = QLabel("生成結果プレビュー（setup.sql。WARNINGコメントの確認、編集・保存ができます）")
        layout.addWidget(preview_label)
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setFixedHeight(160)
        self._preview_highlighter = SqlHighlighter(self.preview_edit.document())
        layout.addWidget(self.preview_edit)

        preview_btn_row = QHBoxLayout()
        self.save_preview_button = QPushButton("保存")
        self.save_preview_button.setObjectName("secondaryButton")
        self.save_preview_button.setEnabled(False)
        self.save_preview_button.clicked.connect(self.on_save_preview)
        preview_btn_row.addWidget(self.save_preview_button)

        self.check_syntax_button = QPushButton("構文を検証（ロールバックのみ・DBは変わりません）")
        self.check_syntax_button.setObjectName("secondaryButton")
        self.check_syntax_button.clicked.connect(self.on_check_syntax)
        preview_btn_row.addWidget(self.check_syntax_button)
        preview_btn_row.addStretch(1)
        layout.addLayout(preview_btn_row)

        execute_row = QHBoxLayout()
        self.execute_setup_button = QPushButton("setup.sqlを実行（DBに反映）")
        self.execute_setup_button.setEnabled(False)
        self.execute_setup_button.clicked.connect(self.on_execute_setup)
        execute_row.addWidget(self.execute_setup_button)

        self.execute_teardown_button = QPushButton("teardown.sqlを実行（DBに反映）")
        self.execute_teardown_button.setObjectName("secondaryButton")
        self.execute_teardown_button.setEnabled(False)
        self.execute_teardown_button.clicked.connect(self.on_execute_teardown)
        execute_row.addWidget(self.execute_teardown_button)
        execute_row.addStretch(1)
        layout.addLayout(execute_row)

        self.preview_status_label = QLabel("")
        self.preview_status_label.setWordWrap(True)
        layout.addWidget(self.preview_status_label)

        self._current_setup_path: "Path | None" = None
        self._current_teardown_path: "Path | None" = None
        self._sql_op_running = False
        self._sql_op_queue: "queue.Queue[str]" = queue.Queue()
        self._sql_op_timer = QTimer(self)
        self._sql_op_timer.timeout.connect(self._poll_sql_op)
        self._sql_op_timer.start(150)

        self.panel.on_finish = self._on_generated

    def stop(self) -> None:
        self._sql_op_timer.stop()

    def _on_generated(self, code: int, path: "Path | None") -> None:
        if code == 0 and path and Path(path).exists():
            self._current_setup_path = Path(path)
            teardown_path = Path(path).parent / "teardown.sql.generated"
            self._current_teardown_path = teardown_path if teardown_path.exists() else None
            self.preview_edit.setPlainText(Path(path).read_text(encoding="utf-8"))
        else:
            self._current_setup_path = None
            self._current_teardown_path = None
            self.preview_edit.clear()
        self._refresh_sql_buttons()

    def _refresh_sql_buttons(self) -> None:
        running = self._sql_op_running
        self.save_preview_button.setEnabled(not running and self._current_setup_path is not None)
        self.check_syntax_button.setEnabled(not running)
        self.execute_setup_button.setEnabled(not running and self._current_setup_path is not None)
        self.execute_teardown_button.setEnabled(not running and self._current_teardown_path is not None)

    def on_save_preview(self) -> None:
        if not self._current_setup_path:
            return
        self._current_setup_path.write_text(self.preview_edit.toPlainText(), encoding="utf-8")
        self.preview_status_label.setText(f"保存しました: {self._current_setup_path}")

    def on_check_syntax(self) -> None:
        self._run_sql_op(self.preview_edit.toPlainText(), validators.check_sql_syntax, "検証中...")

    def on_execute_setup(self) -> None:
        if not self._confirm_execute("setup.sql"):
            return
        # 実行内容とファイルの中身を一致させるため、実行前にプレビューの編集内容を保存しておく
        if self._current_setup_path:
            self._current_setup_path.write_text(self.preview_edit.toPlainText(), encoding="utf-8")
        self._run_sql_op(self.preview_edit.toPlainText(), validators.execute_sql, "実行中...")

    def on_execute_teardown(self) -> None:
        if not self._current_teardown_path or not self._confirm_execute("teardown.sql"):
            return
        sql_text = self._current_teardown_path.read_text(encoding="utf-8")
        self._run_sql_op(sql_text, validators.execute_sql, "実行中...")

    def _confirm_execute(self, label: str) -> bool:
        reply = QMessageBox.warning(
            self, f"{label}の実行確認",
            f"{label}を実際のDBに対して実行します。構文チェックと違い、変更はロールバックされず"
            "そのまま反映されます（TRUNCATE等でデータが失われる可能性があります）。本当に実行しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _run_sql_op(self, sql_text: str, validator_fn, running_label: str) -> None:
        config_path = self.config_field.get()
        self._sql_op_running = True
        self._refresh_sql_buttons()
        self.preview_status_label.setText(running_label)

        def worker() -> None:
            result = validator_fn(sql_text, config_path)
            self._sql_op_queue.put(result)

        threading.Thread(target=worker, daemon=True).start()

    def _poll_sql_op(self) -> None:
        try:
            while True:
                result = self._sql_op_queue.get_nowait()
                self.preview_status_label.setText(result)
                self._sql_op_running = False
                self._refresh_sql_buttons()
        except queue.Empty:
            pass

    def on_validate(self) -> None:
        _show_validation(self, "入力の確認結果", [
            ("DB接続設定", validators.validate_db_config(self.config_field.get())),
        ])

    def save_fields(self) -> None:
        self.settings["sqlgen_config_path"] = self.config_field.get()
        self.settings["sqlgen_schema"] = self.schema_field.get()
        self.settings["sqlgen_tables"] = self.tables_field.get()
        self.settings["sqlgen_output_dir"] = self.output_dir_field.get()

    def on_run(self) -> None:
        config_path = self.config_field.get()
        if not config_path:
            QMessageBox.critical(self, "入力エラー", "DB接続設定 を選択してください")
            return

        output_dir = Path(self.output_dir_field.get() or Path(config_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        setup_output = output_dir / "setup.sql.generated"
        teardown_output = output_dir / "teardown.sql.generated"
        schema = self.schema_field.get()
        tables = self.tables_field.get()

        if not _confirm_overwrite(self, [setup_output, teardown_output]):
            return

        self.save_fields()

        def worker() -> None:
            cmd = [
                sys.executable, "-u", str(GENERATE_SETUP_SQL_PY),
                "--config", config_path,
                "--setup-output", str(setup_output), "--teardown-output", str(teardown_output),
            ]
            if schema:
                cmd += ["--schema", schema]
            if tables:
                cmd += ["--tables", tables]
            code = run_streamed(cmd, self.panel.log_queue, on_start=self.panel.register_process)
            self.panel.finish(code, setup_output if code == 0 else None)

        self.panel.start(worker)


class ScenarioGenTab(QWidget):
    """generate_db_scenarios.py（シナリオYAML雛形生成）を実行するタブ。"""

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings

        layout = QVBoxLayout(self)

        self.openapi_field = PathField("openapi.json", name_filter=JSON_FILTER)
        self.openapi_field.set(settings["scengen_openapi_path"])
        layout.addWidget(self.openapi_field)

        self.mapping_field = PathField("mapping.yaml", name_filter=YAML_FILTER)
        self.mapping_field.set(settings["scengen_mapping_path"])
        layout.addWidget(self.mapping_field)

        self.output_dir_field = PathField("出力先フォルダ", is_dir=True)
        self.output_dir_field.set(settings["scengen_output_dir"])
        layout.addWidget(self.output_dir_field)

        note = QLabel(
            "openapi.jsonとmapping.yamlから、シナリオYAML（scenarios.generated.yaml）の叩き台を"
            "出力します。where/columns/tags等は必ず確認・修正してください。\n"
            "※ここで生成されるのは「API呼び出し後のDB変化」を見るdb_checkのみです。"
            "「DBに事前に仕込んだ値をGET系APIが正しく返すか」を確認したい場合はresponse_check"
            "（このタブでは生成されません）を手書きで追加する必要があります。詳しくはヘルプメニューの"
            "examples/README.mdを参照してください。"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("入力を確認")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate)
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        layout.addLayout(validate_row)

        self.panel = LogPanel(
            "シナリオ雛形生成", self.on_run,
            open_result_label="生成結果を開く", exit_code_meanings=_GENERATOR_EXIT_MEANINGS,
        )
        layout.addWidget(self.panel, stretch=1)

        preview_label = QLabel("生成結果プレビュー（where/columns/tags等をその場で編集・保存できます）")
        layout.addWidget(preview_label)
        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setFixedHeight(160)
        self._preview_highlighter = YamlConfidenceHighlighter(self.preview_edit.document())
        layout.addWidget(self.preview_edit)

        preview_btn_row = QHBoxLayout()
        self.save_preview_button = QPushButton("保存")
        self.save_preview_button.setObjectName("secondaryButton")
        self.save_preview_button.setEnabled(False)
        self.save_preview_button.clicked.connect(self.on_save_preview)
        preview_btn_row.addWidget(self.save_preview_button)
        preview_btn_row.addStretch(1)
        layout.addLayout(preview_btn_row)

        self.preview_status_label = QLabel("")
        self.preview_status_label.setWordWrap(True)
        layout.addWidget(self.preview_status_label)

        self._current_output_path: "Path | None" = None
        self._preview_validate_timer = QTimer(self)
        self._preview_validate_timer.setSingleShot(True)
        self._preview_validate_timer.timeout.connect(self._validate_preview)
        self.preview_edit.textChanged.connect(lambda: self._preview_validate_timer.start(500))

        self.panel.on_finish = self._on_generated

    def _on_generated(self, code: int, path: "Path | None") -> None:
        if code == 0 and path and Path(path).exists():
            self._current_output_path = Path(path)
            self.preview_edit.setPlainText(Path(path).read_text(encoding="utf-8"))
            self.save_preview_button.setEnabled(True)
        else:
            self._current_output_path = None
            self.preview_edit.clear()
            self.save_preview_button.setEnabled(False)

    def _validate_preview(self) -> None:
        self.preview_status_label.setText(validators.validate_scenarios_yaml_text(self.preview_edit.toPlainText()))

    def on_save_preview(self) -> None:
        if not self._current_output_path:
            return
        self._current_output_path.write_text(self.preview_edit.toPlainText(), encoding="utf-8")
        self.preview_status_label.setText(f"保存しました: {self._current_output_path}")

    def on_validate(self) -> None:
        _show_validation(self, "入力の確認結果", [
            ("openapi.json", validators.validate_openapi(self.openapi_field.get())),
            ("mapping.yaml", validators.validate_mapping_yaml(self.mapping_field.get())),
        ])

    def save_fields(self) -> None:
        self.settings["scengen_openapi_path"] = self.openapi_field.get()
        self.settings["scengen_mapping_path"] = self.mapping_field.get()
        self.settings["scengen_output_dir"] = self.output_dir_field.get()

    def on_run(self) -> None:
        openapi_path = self.openapi_field.get()
        mapping_path = self.mapping_field.get()
        if not openapi_path or not mapping_path:
            QMessageBox.critical(self, "入力エラー", "openapi.json と mapping.yaml を選択してください")
            return

        output_dir = Path(self.output_dir_field.get() or Path(openapi_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "scenarios.generated.yaml"

        if not _confirm_overwrite(self, [output_path]):
            return

        self.save_fields()

        def worker() -> None:
            cmd = [
                sys.executable, "-u", str(GENERATE_DB_SCENARIOS_PY), openapi_path, mapping_path,
                "-o", str(output_path),
            ]
            code = run_streamed(cmd, self.panel.log_queue, on_start=self.panel.register_process)
            self.panel.finish(code, output_path if code == 0 else None)

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

        health_note = QLabel(
            "対象APIの疎通確認に使うパスです。ここが200番台を返さないと試験は1件も実行されず、"
            "「ヘルスチェック失敗」で即座に中断します。対象APIに/healthが無い場合は、GETで200番台が"
            "返る既存のパス（例: /、または対象APIの一覧取得系エンドポイントなど）に変更してください。"
        )
        health_note.setWordWrap(True)
        layout.addWidget(health_note)

        self.auth_config_field = PathField("認証設定(任意)", name_filter=JSON_FILTER)
        self.auth_config_field.set(settings["db_auth_config_path"])
        layout.addWidget(self.auth_config_field)

        self.dry_run_checkbox = QCheckBox("dry-run（実際にはAPIリクエスト送信・DB接続を行わない。設定内容の確認用）")
        self.dry_run_checkbox.setChecked(bool(settings["db_dry_run"]))
        layout.addWidget(self.dry_run_checkbox)

        self.report_dir_field = PathField("レポート出力先フォルダ(任意)", is_dir=True)
        self.report_dir_field.set(settings["db_report_dir"])
        layout.addWidget(self.report_dir_field)

        validate_row = QHBoxLayout()
        self.validate_button = QPushButton("入力を確認")
        self.validate_button.setObjectName("secondaryButton")
        self.validate_button.clicked.connect(self.on_validate)
        validate_row.addWidget(self.validate_button)
        validate_row.addStretch(1)
        layout.addLayout(validate_row)

        self.connectivity_row = ConnectivityCheckRow(self.config_field.get)
        layout.addWidget(self.connectivity_row)

        self.panel = LogPanel("実行", self.on_run, open_result_label="結果Excelを開く")
        layout.addWidget(self.panel, stretch=1)

    def on_validate(self) -> None:
        _show_validation(self, "入力の確認結果", [
            ("シナリオYAML", validators.validate_scenarios_yaml(self.scenario_field.get())),
            ("openapi.json", validators.validate_openapi(self.openapi_field.get())),
            ("config.json", validators.validate_db_config(self.config_field.get())),
            ("認証設定", validators.validate_auth_config(self.auth_config_field.get())),
        ])

    def save_fields(self) -> None:
        self.settings["db_scenario_path"] = self.scenario_field.get()
        self.settings["db_openapi_path"] = self.openapi_field.get()
        self.settings["db_config_path"] = self.config_field.get()
        self.settings["db_base_url"] = self.base_url_field.get()
        self.settings["db_health_path"] = self.health_path_field.get()
        self.settings["db_auth_config_path"] = self.auth_config_field.get()
        self.settings["db_dry_run"] = self.dry_run_checkbox.isChecked()
        self.settings["db_report_dir"] = self.report_dir_field.get()

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
        report_dir = self.report_dir_field.get()
        report_path = Path(report_dir) / "db_scenario_result.xlsx" if report_dir else None
        if report_path and not _confirm_overwrite(self, [report_path]):
            return

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
            if report_path:
                Path(report_dir).mkdir(parents=True, exist_ok=True)
                cmd += ["--report-output", str(report_path)]
            code = run_streamed(cmd, self.panel.log_queue, on_start=self.panel.register_process)
            self.panel.finish(code, report_path if (report_path and code in (0, 1)) else None)

        self.panel.start(worker)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("openapi-test-gen / openapi-test-run")
        self.resize(960, 720)

        self.settings = load_settings()
        self._build_help_menu()

        tabs = QTabWidget()
        self.gen_tab = GenerateRunTab(self.settings)
        self.config_builder_tab = ConfigBuilderTab(self.settings)
        self.auth_builder_tab = AuthConfigBuilderTab(self.settings)
        self.mapping_gen_tab = MappingGenTab(self.settings)
        self.sql_gen_tab = SetupSqlGenTab(self.settings)
        self.scenario_gen_tab = ScenarioGenTab(self.settings)
        self.db_tab = DBScenarioTab(self.settings)

        db_prep_tabs = QTabWidget()
        db_prep_tabs.addTab(self.config_builder_tab, "①DB接続設定")
        db_prep_tabs.addTab(self.auth_builder_tab, "②認証設定(任意)")
        db_prep_tabs.addTab(self.mapping_gen_tab, "③mapping.yaml")
        db_prep_tabs.addTab(self.sql_gen_tab, "④setup.sql/teardown.sql")
        db_prep_tabs.addTab(self.scenario_gen_tab, "⑤シナリオ雛形")

        db_prep_container = QWidget()
        db_prep_layout = QVBoxLayout(db_prep_container)
        db_prep_layout.setContentsMargins(0, 0, 0, 0)
        intro_label = QLabel(
            "DB検証（Layer2）の準備はこの順番で進めます: "
            "①DB接続設定 → ②認証設定(任意) → ③mapping.yaml → ④setup.sql/teardown.sql → ⑤シナリオ雛形。"
            "各ステップで生成・保存したファイルは、次のステップの入力欄に自動で反映されます。"
            "④は生成・保存しただけではDBに反映されません。「実行（DBに反映）」ボタンを別途押してください。"
            "完了したら「DBシナリオ」タブで実行してください。"
        )
        intro_label.setWordWrap(True)
        intro_label.setObjectName("introLabel")
        db_prep_layout.addWidget(intro_label)
        db_prep_layout.addWidget(db_prep_tabs)

        tabs.addTab(self.gen_tab, "テスト生成・実行")
        tabs.addTab(db_prep_container, "DB準備")
        tabs.addTab(self.db_tab, "DBシナリオ")

        self._all_tabs = (
            self.gen_tab, self.config_builder_tab, self.auth_builder_tab,
            self.mapping_gen_tab, self.sql_gen_tab, self.scenario_gen_tab, self.db_tab,
        )
        self._wire_cross_tab_propagation()

        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.addWidget(tabs)
        self.setCentralWidget(container)

    def _build_help_menu(self) -> None:
        """DB検証(Layer2)のDSL（response_check等）はGUIの案内文だけでは説明しきれないため、
        リポジトリ内の詳細ドキュメントを開く導線をヘルプメニューとして用意する。"""
        help_menu = self.menuBar().addMenu("ヘルプ")

        examples_action = QAction("使い方の例（examples/README.md）を開く", self)
        examples_action.triggered.connect(
            lambda: self._open_doc(REPO_ROOT / "examples" / "README.md")
        )
        help_menu.addAction(examples_action)

        runner_action = QAction("DB検証(Layer2)の詳細（runner/README.md）を開く", self)
        runner_action.triggered.connect(
            lambda: self._open_doc(REPO_ROOT / "runner" / "README.md")
        )
        help_menu.addAction(runner_action)

    def _open_doc(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "ファイルが見つかりません", f"{path} が見つかりませんでした。")
            return
        os.startfile(str(path))  # noqa: S606 - Windows専用ツールのため

    def _wire_cross_tab_propagation(self) -> None:
        """あるタブで生成・保存したファイルのパスを、次のステップのタブへ自動反映する。"""

        def propagate_config(path: Path) -> None:
            for tab in (self.mapping_gen_tab, self.sql_gen_tab, self.db_tab, self.gen_tab):
                tab.config_field.set(str(path))

        def propagate_auth(path: Path) -> None:
            for tab in (self.gen_tab, self.db_tab):
                tab.auth_config_field.set(str(path))

        def propagate_mapping(code: int, path: "Path | None") -> None:
            if code == 0 and path:
                self.scenario_gen_tab.mapping_field.set(str(path))

        def propagate_setup_sql(code: int, path: "Path | None") -> None:
            if code == 0 and path:
                self.gen_tab.setup_field.set(str(path))
                teardown_path = Path(path).parent / "teardown.sql.generated"
                if teardown_path.exists():
                    self.gen_tab.teardown_field.set(str(teardown_path))

        def propagate_scenario(code: int, path: "Path | None") -> None:
            if code == 0 and path:
                self.db_tab.scenario_field.set(str(path))

        self.config_builder_tab.on_saved = propagate_config
        self.auth_builder_tab.on_saved = propagate_auth

        self._chain_on_finish(self.mapping_gen_tab.panel, propagate_mapping)
        self._chain_on_finish(self.sql_gen_tab.panel, propagate_setup_sql)
        self._chain_on_finish(self.scenario_gen_tab.panel, propagate_scenario)

    @staticmethod
    def _chain_on_finish(panel: "LogPanel", extra_callback) -> None:
        """panel.on_finish に既存のハンドラ（プレビュー更新等）を残したまま、追加のコールバックを連結する。"""
        original = panel.on_finish

        def combined(code: int, path: "Path | None") -> None:
            if original:
                original(code, path)
            extra_callback(code, path)

        panel.on_finish = combined

    def closeEvent(self, event) -> None:  # noqa: N802 - Qtのオーバーライド規約
        running_panels = [tab.panel for tab in self._all_tabs if hasattr(tab, "panel") and tab.panel.is_running()]
        if running_panels:
            reply = QMessageBox.question(
                self, "実行中の処理があります",
                "実行中の処理があります。終了すると処理が強制終了されます。終了してもよろしいですか？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

        for tab in self._all_tabs:
            tab.save_fields()
        save_settings(self.settings)
        for tab in self._all_tabs:
            if hasattr(tab, "panel"):
                tab.panel.stop()
            if hasattr(tab, "connectivity_row"):
                tab.connectivity_row.stop()
            if hasattr(tab, "stop"):
                tab.stop()
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
