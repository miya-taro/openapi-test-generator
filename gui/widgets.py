"""共通で使う入力フィールド部品。"""
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog


class PathField(ttk.Frame):
    """ファイル/フォルダ選択付きの入力欄。"""

    def __init__(self, parent, label: str, is_dir: bool = False, filetypes=None, width: int = 16):
        super().__init__(parent)
        self.is_dir = is_dir
        self.filetypes = filetypes or [("すべてのファイル", "*.*")]
        self.var = tk.StringVar()

        ttk.Label(self, text=label, width=width, anchor="w").pack(side="left")
        ttk.Entry(self, textvariable=self.var).pack(side="left", fill="x", expand=True, padx=(4, 4))
        ttk.Button(self, text="参照...", command=self._browse).pack(side="left")

    def _browse(self) -> None:
        path = filedialog.askdirectory() if self.is_dir else filedialog.askopenfilename(filetypes=self.filetypes)
        if path:
            self.var.set(path)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value or "")


class TextField(ttk.Frame):
    """単純なテキスト入力欄。"""

    def __init__(self, parent, label: str, default: str = "", width: int = 16):
        super().__init__(parent)
        self.var = tk.StringVar(value=default)
        ttk.Label(self, text=label, width=width, anchor="w").pack(side="left")
        ttk.Entry(self, textvariable=self.var).pack(side="left", fill="x", expand=True, padx=(4, 4))

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value or "")
