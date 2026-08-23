import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import settings as settings_module
from settings import load_settings, save_settings, DEFAULTS


def test_load_settings_returns_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", tmp_path / "nope.json")
    loaded = load_settings()
    assert loaded == DEFAULTS


def test_save_then_load_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)

    to_save = {**DEFAULTS, "gen_base_url": "http://example.com", "gen_openapi_path": "C:/x/openapi.json"}
    save_settings(to_save)

    loaded = load_settings()
    assert loaded["gen_base_url"] == "http://example.com"
    assert loaded["gen_openapi_path"] == "C:/x/openapi.json"


def test_load_settings_merges_missing_keys_with_defaults(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text('{"gen_base_url": "http://only-this-key.example"}', encoding="utf-8")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)

    loaded = load_settings()
    assert loaded["gen_base_url"] == "http://only-this-key.example"
    assert loaded["gen_health_path"] == DEFAULTS["gen_health_path"]  # 欠けているキーはデフォルトで補完


def test_load_settings_falls_back_to_defaults_on_invalid_json(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", path)

    loaded = load_settings()
    assert loaded == DEFAULTS


def test_save_settings_does_not_raise_when_directory_unwritable(monkeypatch):
    monkeypatch.setattr(settings_module, "SETTINGS_PATH", Path("Z:/does/not/exist/settings.json"))
    save_settings(dict(DEFAULTS))  # 例外を送出しないことのみ確認
