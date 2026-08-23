#!/usr/bin/env python3
"""openapi-test-gen / openapi-test-run / db_scenario_runner をGUIから操作するデスクトップアプリ。

既存のCLIツール群をそのままサブプロセスとして呼び出す薄いラッパー。
CLI自体はこれまで通り単独でも使用できる。
"""
from __future__ import annotations
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, scrolledtext

sys.path.insert(0, str(Path(__file__).resolve().parent))
from settings import load_settings, save_settings
from widgets import PathField, TextField
from process_runner import run_streamed, exit_code_meaning

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PY = REPO_ROOT / "src" / "cli.py"
RUNNER_PY = REPO_ROOT / "runner" / "runner.py"
DB_SCENARIO_RUNNER_PY = REPO_ROOT / "runner" / "db_scenario_runner.py"

JSON_FILETYPES = [("JSON", "*.json"), ("すべてのファイル", "*.*")]
YAML_FILETYPES = [("YAML", "*.yaml;*.yml"), ("すべてのファイル", "*.*")]


class LogPanel(ttk.Frame):
    """ログ表示 + ステータス行 + 実行ボタン群を持つ共通の下部パネル。"""

    def __init__(self, parent, run_label: str, on_run):
        super().__init__(parent)
        self.on_run = on_run
        self.log_queue: "queue.Queue[tuple]" = queue.Queue()

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", pady=(6, 2))
        self.run_button = ttk.Button(btn_frame, text=run_label, command=self._on_run_clicked)
        self.run_button.pack(side="left")
        self.open_result_button = ttk.Button(
            btn_frame, text="結果Excelを開く", command=self._open_result, state="disabled"
        )
        self.open_result_button.pack(side="left", padx=(6, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var).pack(fill="x")

        self.log_widget = scrolledtext.ScrolledText(self, height=24, state="disabled")
        self.log_widget.pack(fill="both", expand=True, pady=(4, 0))

        self.result_path: Path | None = None
        self._after_id: str | None = None
        self._poll_queue()

    def stop(self) -> None:
        """ウィンドウを閉じる前に呼び、スケジュール済みの after コールバックを止める。"""
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _on_run_clicked(self) -> None:
        self.on_run()

    def start(self, worker) -> None:
        self._clear_log()
        self.run_button.configure(state="disabled")
        self.open_result_button.configure(state="disabled")
        self.result_path = None
        self.status_var.set("実行中...")
        threading.Thread(target=worker, daemon=True).start()

    def finish(self, code: int, result_path: Path | None) -> None:
        self.log_queue.put(("final", code, result_path))

    def _append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if item[0] == "line":
                    self._append_log(item[1])
                elif item[0] == "final":
                    code, result_path = item[1], item[2]
                    self.status_var.set(exit_code_meaning(code))
                    self.run_button.configure(state="normal")
                    self.result_path = result_path
                    if result_path and Path(result_path).exists():
                        self.open_result_button.configure(state="normal")
        except queue.Empty:
            pass
        self._after_id = self.after(100, self._poll_queue)

    def _open_result(self) -> None:
        if self.result_path and self.result_path.exists():
            os.startfile(str(self.result_path))  # noqa: S606 - Windows専用ツールのため


class GenerateRunTab(ttk.Frame):
    """openapi-test-gen で生成 → openapi-test-run で実行、を1クリックで行うタブ。"""

    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.settings = settings

        self.openapi_field = PathField(self, "openapi.json", filetypes=JSON_FILETYPES)
        self.openapi_field.set(settings["gen_openapi_path"])
        self.openapi_field.pack(fill="x", padx=8, pady=2)

        self.output_dir_field = PathField(self, "出力先フォルダ", is_dir=True)
        self.output_dir_field.set(settings["gen_output_dir"])
        self.output_dir_field.pack(fill="x", padx=8, pady=2)

        self.base_url_field = TextField(self, "Base URL", settings["gen_base_url"])
        self.base_url_field.pack(fill="x", padx=8, pady=2)

        self.health_path_field = TextField(self, "Health Path", settings["gen_health_path"])
        self.health_path_field.pack(fill="x", padx=8, pady=2)

        self.panel = LogPanel(self, "生成して実行", self.on_run)
        self.panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def save_fields(self) -> None:
        self.settings["gen_openapi_path"] = self.openapi_field.get()
        self.settings["gen_output_dir"] = self.output_dir_field.get()
        self.settings["gen_base_url"] = self.base_url_field.get()
        self.settings["gen_health_path"] = self.health_path_field.get()

    def on_run(self) -> None:
        openapi_path = self.openapi_field.get()
        base_url = self.base_url_field.get()
        if not openapi_path:
            messagebox.showerror("入力エラー", "openapi.json を選択してください")
            return
        if not base_url:
            messagebox.showerror("入力エラー", "Base URL を入力してください")
            return

        output_dir = Path(self.output_dir_field.get() or Path(openapi_path).resolve().parent)
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_path = output_dir / "試験仕様.xlsx"
        cases_path = output_dir / "test_cases.json"
        result_path = output_dir / "試験仕様_result.xlsx"
        health_path = self.health_path_field.get() or "/health"

        self.save_fields()

        def worker() -> None:
            gen_cmd = [
                sys.executable, str(CLI_PY), openapi_path,
                "-o", str(cases_path), "--excel-output", str(spec_path),
            ]
            code = run_streamed(gen_cmd, self.panel.log_queue)
            if code != 0:
                self.panel.log_queue.put(("line", f"[ERROR] テスト仕様の生成に失敗しました（終了コード {code}）"))
                self.panel.finish(code, None)
                return

            self.panel.log_queue.put(("line", ""))
            run_cmd = [
                sys.executable, str(RUNNER_PY), str(spec_path), openapi_path,
                "--base-url", base_url, "--health-path", health_path,
                "--output", str(result_path),
            ]
            code = run_streamed(run_cmd, self.panel.log_queue)
            self.panel.finish(code, result_path)

        self.panel.start(worker)


class DBScenarioTab(ttk.Frame):
    """db_scenario_runner.py を実行するタブ。"""

    def __init__(self, parent, settings: dict):
        super().__init__(parent)
        self.settings = settings

        self.scenario_field = PathField(self, "シナリオYAML", filetypes=YAML_FILETYPES)
        self.scenario_field.set(settings["db_scenario_path"])
        self.scenario_field.pack(fill="x", padx=8, pady=2)

        self.openapi_field = PathField(self, "openapi.json", filetypes=JSON_FILETYPES)
        self.openapi_field.set(settings["db_openapi_path"])
        self.openapi_field.pack(fill="x", padx=8, pady=2)

        self.config_field = PathField(self, "config.json", filetypes=JSON_FILETYPES)
        self.config_field.set(settings["db_config_path"])
        self.config_field.pack(fill="x", padx=8, pady=2)

        self.base_url_field = TextField(self, "Base URL", settings["db_base_url"])
        self.base_url_field.pack(fill="x", padx=8, pady=2)

        self.health_path_field = TextField(self, "Health Path", settings["db_health_path"])
        self.health_path_field.pack(fill="x", padx=8, pady=2)

        self.panel = LogPanel(self, "実行", self.on_run)
        self.panel.open_result_button.pack_forget()  # DBシナリオは結果Excelを出力しないため非表示
        self.panel.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    def save_fields(self) -> None:
        self.settings["db_scenario_path"] = self.scenario_field.get()
        self.settings["db_openapi_path"] = self.openapi_field.get()
        self.settings["db_config_path"] = self.config_field.get()
        self.settings["db_base_url"] = self.base_url_field.get()
        self.settings["db_health_path"] = self.health_path_field.get()

    def on_run(self) -> None:
        scenario_path = self.scenario_field.get()
        openapi_path = self.openapi_field.get()
        config_path = self.config_field.get()
        base_url = self.base_url_field.get()
        if not scenario_path or not openapi_path or not config_path:
            messagebox.showerror("入力エラー", "シナリオYAML・openapi.json・config.json をすべて選択してください")
            return
        if not base_url:
            messagebox.showerror("入力エラー", "Base URL を入力してください")
            return

        health_path = self.health_path_field.get() or "/health"
        self.save_fields()

        def worker() -> None:
            cmd = [
                sys.executable, str(DB_SCENARIO_RUNNER_PY), scenario_path, openapi_path,
                "--base-url", base_url, "--config", config_path, "--health-path", health_path,
            ]
            code = run_streamed(cmd, self.panel.log_queue)
            self.panel.finish(code, None)

        self.panel.start(worker)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("openapi-test-gen / openapi-test-run")
        self.geometry("900x700")
        self.minsize(700, 500)

        self.settings = load_settings()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.gen_tab = GenerateRunTab(notebook, self.settings)
        self.db_tab = DBScenarioTab(notebook, self.settings)
        notebook.add(self.gen_tab, text="テスト生成・実行")
        notebook.add(self.db_tab, text="DBシナリオ")

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self.gen_tab.save_fields()
        self.db_tab.save_fields()
        save_settings(self.settings)
        self.gen_tab.panel.stop()
        self.db_tab.panel.stop()
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
