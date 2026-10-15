"""A damaged settings file must be visible and recoverable in the real UI."""
import json
import os
import shutil
import threading
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("OTG_BROWSER_TEST") != "1", reason="requires built UI and Chromium")
@pytest.mark.parametrize("with_backup", [True, False])
def test_browser_settings_recovery(tmp_path, monkeypatch, with_backup):
    from gui import web_server
    from playwright.sync_api import expect, sync_playwright

    root = Path(__file__).parents[2]
    for name in ("DATA", "IMPORTS", "SAVED", "OUTPUT", "TEMP"):
        path = tmp_path / name.lower()
        path.mkdir()
        monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, "SETTINGS", tmp_path / "settings.json")
    state = web_server.WebState(root / "gui-tauri/dist")
    if with_backup:
        for url in ("http://previous.test", "http://latest.test"):
            state.invoke("save_settings", {"data": {"gen_base_url": url}})
    web_server.SETTINGS.write_bytes(b'{"broken":')
    host = web_server.WebServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which("chromium"), args=["--no-sandbox"])
            try:
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{host.server_port}/")
                page.locator('[data-step="target"]').click()
                expect(page.locator("#settings-status")).to_contain_text("バックアップ" if with_backup else "復元できません")
                expect(page.locator("#base-url")).to_have_value("http://previous.test" if with_backup else "")
                assert web_server.SETTINGS.read_bytes() == b'{"broken":'
                page.locator("#base-url").fill("http://confirmed.test")
                page.locator("#settings-save").click()
                expect(page.locator("#settings-status")).to_contain_text("保存しました")
                saved = json.loads(web_server.SETTINGS.read_text())
                assert saved["gen_base_url"] == "http://confirmed.test"
                assert "_settings_warning" not in saved
                assert [p.read_bytes() for p in tmp_path.glob("*.corrupt-*")] == [b'{"broken":']
                page.reload()
                page.locator('[data-step="target"]').click()
                expect(page.locator("#settings-status")).to_contain_text("復元しました")
                expect(page.locator("#base-url")).to_have_value("http://confirmed.test")
                assert not errors
            finally:
                browser.close()
    finally:
        host.shutdown()
        host.server_close()
        thread.join(timeout=5)
