"""Settings remain recoverable after an interrupted write or damaged file."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from gui import web_server


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, "SETTINGS", tmp_path / "settings.json")
    return web_server.WebState(tmp_path)


def test_settings_recover_backup_without_silently_overwriting_original(store):
    first = {"gen_base_url": "http://first.test", "shared_openapi_path": "日本語.json"}
    second = {"gen_base_url": "http://second.test"}
    assert store.invoke("load_settings", {}) == {}
    store.invoke("save_settings", {"data": first})
    store.invoke("save_settings", {"data": second})
    path = web_server.SETTINGS
    path.write_bytes(b'{"broken":')
    recovered = store.invoke("load_settings", {})
    assert recovered["gen_base_url"] == first["gen_base_url"]
    assert "バックアップ" in recovered["_settings_warning"]
    assert path.read_bytes() == b'{"broken":'
    store.invoke("save_settings", {"data": recovered})
    assert store.invoke("load_settings", {}) == first
    assert json.loads(path.with_name(path.name + ".bak").read_text()) == first
    assert [p.read_bytes() for p in path.parent.glob("*.corrupt-*")] == [b'{"broken":']
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("contents", [b'{', b'[]', b'null', b'123', b'\xff'])
def test_unrecoverable_settings_report_error_and_preserve_file(store, contents):
    web_server.SETTINGS.write_bytes(contents)
    with pytest.raises(ValueError, match="バックアップもありません"):
        store.invoke("load_settings", {})
    assert web_server.SETTINGS.read_bytes() == contents


def test_interrupted_replacement_keeps_previous_settings(store, monkeypatch):
    store.invoke("save_settings", {"data": {"gen_base_url": "http://original.test"}})
    original_replace = web_server.os.replace

    def fail_settings_replace(source, destination):
        if destination == web_server.SETTINGS:
            raise OSError("disk failure")
        original_replace(source, destination)

    monkeypatch.setattr(web_server.os, "replace", fail_settings_replace)
    with pytest.raises(OSError, match="disk failure"):
        store.invoke("save_settings", {"data": {"gen_base_url": "http://new.test"}})
    assert store.invoke("load_settings", {}) == {"gen_base_url": "http://original.test"}
    assert not list(web_server.SETTINGS.parent.glob("*.tmp"))


def test_concurrent_saves_keep_valid_settings_and_backup(store):
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda number: store.invoke("save_settings", {"data": {"number": number}}), range(20)))
    assert store.invoke("load_settings", {})["number"] in range(20)
    path = web_server.SETTINGS
    assert json.loads(path.with_name(path.name + ".bak").read_text())["number"] in range(20)


def test_missing_main_file_recovers_backup(store):
    for number in (1, 2):
        store.invoke("save_settings", {"data": {"number": number}})
    web_server.SETTINGS.unlink()
    assert store.invoke("load_settings", {})["number"] == 1
