"""共通で使う入力フィールド部品（PySide6）。"""
from __future__ import annotations
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog


class PathField(QWidget):
    """ファイル/フォルダ選択付きの入力欄。"""

    def __init__(
        self, label: str, is_dir: bool = False, name_filter: str = "すべてのファイル (*.*)",
        for_saving: bool = False, placeholder: str = "", parent=None,
    ):
        super().__init__(parent)
        self.is_dir = is_dir
        self.name_filter = name_filter
        self.for_saving = for_saving

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label_widget = QLabel(label)
        label_widget.setMinimumWidth(120)
        layout.addWidget(label_widget)

        self.line_edit = QLineEdit()
        if placeholder:
            self.line_edit.setPlaceholderText(placeholder)
        layout.addWidget(self.line_edit, stretch=1)

        browse_button = QPushButton("参照...")
        browse_button.setObjectName("secondaryButton")
        browse_button.clicked.connect(self._browse)
        layout.addWidget(browse_button)

    def _browse(self) -> None:
        if self.is_dir:
            path = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        elif self.for_saving:
            path, _ = QFileDialog.getSaveFileName(self, "保存先を選択", filter=self.name_filter)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "ファイルを選択", filter=self.name_filter)
        if path:
            self.line_edit.setText(path)

    def get(self) -> str:
        return self.line_edit.text().strip()

    def set(self, value: str) -> None:
        self.line_edit.setText(value or "")


class TextField(QWidget):
    """単純なテキスト入力欄。"""

    def __init__(self, label: str, default: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label_widget = QLabel(label)
        label_widget.setMinimumWidth(120)
        layout.addWidget(label_widget)

        self.line_edit = QLineEdit(default)
        if placeholder:
            self.line_edit.setPlaceholderText(placeholder)
        layout.addWidget(self.line_edit, stretch=1)

    def get(self) -> str:
        return self.line_edit.text().strip()

    def set(self, value: str) -> None:
        self.line_edit.setText(value or "")
