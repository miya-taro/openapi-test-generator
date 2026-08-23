import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication, QFileDialog

from widgets import PathField

_app = QApplication.instance() or QApplication([])


def test_path_field_open_mode_uses_get_open_file_name(monkeypatch):
    calls = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (calls.append("open"), ("picked.json", ""))[1])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (calls.append("save"), ("x", ""))[1])
    field = PathField("入力", for_saving=False)
    field._browse()
    assert calls == ["open"]
    assert field.get() == "picked.json"


def test_path_field_save_mode_uses_get_save_file_name(monkeypatch):
    calls = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (calls.append("open"), ("x", ""))[1])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (calls.append("save"), ("out.json", ""))[1])
    field = PathField("出力", for_saving=True)
    field._browse()
    assert calls == ["save"]
    assert field.get() == "out.json"


def test_path_field_dir_mode_uses_get_existing_directory(monkeypatch):
    calls = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: (calls.append("dir"), "some/dir")[1])
    field = PathField("フォルダ", is_dir=True)
    field._browse()
    assert calls == ["dir"]
    assert field.get() == "some/dir"
