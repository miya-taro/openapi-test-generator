"""ConfigBuilderTab（DB接続設定）/ AuthConfigBuilderTab（認証設定）の保存・読み込みを検証する。"""
import json
import sys
import time
from pathlib import Path

import pytest
import yaml

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


# ---------- ConfigBuilderTab ----------


def test_config_builder_save_postgres_only(window, tmp_path):
    tab = window.config_builder_tab
    output_path = tmp_path / "config.json"
    tab.output_path_field.set(str(output_path))
    tab.pg_checkbox.setChecked(True)
    tab.pg_host.set("localhost")
    tab.pg_port.set("5432")
    tab.pg_dbname.set("testdb")
    tab.pg_user.set("u")
    tab.pg_password.set("p")
    tab.influx_checkbox.setChecked(False)

    tab.on_save()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data == {"postgres": {"host": "localhost", "port": 5432, "dbname": "testdb", "user": "u", "password": "p"}}
    assert "OK" in tab.status_label.text()


def test_config_builder_save_both_engines(window, tmp_path):
    tab = window.config_builder_tab
    output_path = tmp_path / "config.json"
    tab.output_path_field.set(str(output_path))
    tab.pg_checkbox.setChecked(True)
    tab.pg_host.set("h")
    tab.pg_port.set("5432")
    tab.pg_dbname.set("d")
    tab.pg_user.set("u")
    tab.pg_password.set("p")
    tab.influx_checkbox.setChecked(True)
    tab.influx_host.set("ih")
    tab.influx_port.set("8086")
    tab.influx_database.set("idb")

    tab.on_save()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "postgres" in data
    assert data["influxdb"] == {"host": "ih", "port": 8086, "database": "idb"}


def test_config_builder_influx_optional_username_password_omitted_when_blank(window, tmp_path):
    tab = window.config_builder_tab
    output_path = tmp_path / "config.json"
    tab.output_path_field.set(str(output_path))
    tab.pg_checkbox.setChecked(False)
    tab.influx_checkbox.setChecked(True)
    tab.influx_host.set("h")
    tab.influx_port.set("8086")
    tab.influx_database.set("d")

    tab.on_save()

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "username" not in data["influxdb"]
    assert "password" not in data["influxdb"]


def test_config_builder_rejects_non_numeric_port(window, tmp_path, monkeypatch):
    tab = window.config_builder_tab
    tab.output_path_field.set(str(tmp_path / "config.json"))
    tab.pg_checkbox.setChecked(True)
    tab.pg_host.set("h")
    tab.pg_port.set("not-a-number")
    tab.pg_dbname.set("d")
    tab.pg_user.set("u")
    tab.pg_password.set("p")

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_save()
    assert len(shown) == 1
    assert not (tmp_path / "config.json").exists()


def test_config_builder_requires_at_least_one_engine(window, tmp_path, monkeypatch):
    tab = window.config_builder_tab
    tab.output_path_field.set(str(tmp_path / "config.json"))
    tab.pg_checkbox.setChecked(False)
    tab.influx_checkbox.setChecked(False)

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_save()
    assert len(shown) == 1


def test_config_builder_password_not_persisted_to_settings(window, tmp_path):
    tab = window.config_builder_tab
    tab.pg_password.set("super-secret")
    tab.save_fields()
    assert "super-secret" not in json.dumps(window.settings)


def test_config_builder_load_populates_fields(window, tmp_path):
    cfg = {"postgres": {"host": "h", "port": 1234, "dbname": "d", "user": "u", "password": "p"}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")

    tab = window.config_builder_tab
    tab.output_path_field.set(str(path))
    tab.on_load()

    assert tab.pg_checkbox.isChecked() is True
    assert tab.pg_host.get() == "h"
    assert tab.pg_port.get() == "1234"
    assert tab.influx_checkbox.isChecked() is False


def test_config_builder_load_missing_file_shows_error(window, tmp_path, monkeypatch):
    tab = window.config_builder_tab
    tab.output_path_field.set(str(tmp_path / "missing.json"))

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_load()
    assert len(shown) == 1


# ---------- AuthConfigBuilderTab ----------


def test_auth_builder_save_minimal(window, tmp_path):
    tab = window.auth_builder_tab
    output_path = tmp_path / "auth.yaml"
    tab.output_path_field.set(str(output_path))
    tab.login_url_field.set("/login")

    tab.on_save()

    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert data["login_url"] == "/login"
    assert data["method"] == "POST"
    assert data["token_path"] == "access_token"
    assert "OK" in tab.status_label.text()


def test_auth_builder_save_with_body(window, tmp_path):
    tab = window.auth_builder_tab
    output_path = tmp_path / "auth.yaml"
    tab.output_path_field.set(str(output_path))
    tab.login_url_field.set("/login")
    tab.body_edit.setPlainText('{"username": "u", "password": "p"}')

    tab.on_save()

    data = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert data["body"] == {"username": "u", "password": "p"}


def test_auth_builder_invalid_body_json_shows_error(window, tmp_path, monkeypatch):
    tab = window.auth_builder_tab
    tab.output_path_field.set(str(tmp_path / "auth.yaml"))
    tab.login_url_field.set("/login")
    tab.body_edit.setPlainText("{not json")

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_save()
    assert len(shown) == 1
    assert not (tmp_path / "auth.yaml").exists()


def test_auth_builder_requires_login_url(window, tmp_path, monkeypatch):
    tab = window.auth_builder_tab
    tab.output_path_field.set(str(tmp_path / "auth.yaml"))

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_save()
    assert len(shown) == 1


def test_auth_builder_load_populates_fields(window, tmp_path):
    path = tmp_path / "auth.yaml"
    path.write_text(
        "login_url: /api/login\nmethod: PUT\nbody:\n  a: 1\ntoken_path: token\n"
        "header_name: X-Token\nheader_format: '{token}'\n",
        encoding="utf-8",
    )
    tab = window.auth_builder_tab
    tab.output_path_field.set(str(path))
    tab.on_load()

    assert tab.login_url_field.get() == "/api/login"
    assert tab.method_combo.currentText() == "PUT"
    assert tab.token_path_field.get() == "token"
    assert tab.header_name_field.get() == "X-Token"
    assert '"a": 1' in tab.body_edit.toPlainText()


def test_auth_builder_load_invalid_shows_error(window, tmp_path, monkeypatch):
    path = tmp_path / "auth.yaml"
    path.write_text("login_url: /login\n", encoding="utf-8")  # methodが無い
    tab = window.auth_builder_tab
    tab.output_path_field.set(str(path))

    shown = []
    monkeypatch.setattr(app_module.QMessageBox, "critical", lambda *a, **k: shown.append(a))
    tab.on_load()
    assert len(shown) == 1
