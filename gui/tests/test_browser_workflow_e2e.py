"""Opt-in real Chromium test: import, approve, run, download, fail and rerun."""
import os
import shutil
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))


@pytest.mark.skipif(os.environ.get("OTG_BROWSER_TEST") != "1", reason="requires built UI and Chromium")
def test_browser_workflow(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server
    from docs.release_candidate_api import CandidateServer

    output = Path(os.environ.get("OTG_BROWSER_EVIDENCE_DIR", str(tmp_path / "evidence")))
    output.mkdir(parents=True, exist_ok=True)
    for name in ("DATA", "IMPORTS", "SAVED", "OUTPUT", "TEMP"):
        path = tmp_path / "app" / name.lower()
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, "SETTINGS", tmp_path / "settings.json")
    api = CandidateServer()
    host = web_server.WebServer(("127.0.0.1", 0), web_server.WebState(ROOT / "gui-tauri/dist"))
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (api, host)]
    for thread in threads:
        thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("OTG_BROWSER_EXECUTABLE") or shutil.which("chromium") or shutil.which("google-chrome"),
                headless=True, args=["--no-sandbox"],
            )
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(60000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(f"http://127.0.0.1:{host.server_port}/")
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser:
                    page.locator("#browse-openapi").click()
                chooser.value.set_files(ROOT / "docs/release_candidate_openapi.json")
                expect(page.locator("#operations-list input[data-op-id]")).to_have_count(12)
                page.locator("#base-url").fill(f"http://127.0.0.1:{api.server_port}")
                page.locator("#output-dir").fill(str(tmp_path / "results"))
                page.locator("#ops-select-none").click()
                page.locator('#operations-list input[data-op-id="emptyOk"]').check()
                page.locator('[data-step="run"]').click()
                page.locator("#run-button").click()
                expect(page.locator("#run-status")).to_contain_text("ケース準備完了", timeout=120000)
                assert not api.calls, "Preparing a case must not call the target API"
                page.get_by_role("button", name="レビュー済みにする", exact=True).click()
                page.get_by_role("button", name="承認する", exact=True).click()

                def download_result(name, expected):
                    with page.expect_download() as download:
                        page.locator("#open-result-button").click()
                    destination = output / f"{name}.xlsx"
                    download.value.save_as(destination)
                    workbook = load_workbook(destination, read_only=True)
                    try:
                        values = [value for sheet in workbook for row in sheet.values for value in row]
                        assert expected in values, values
                    finally:
                        workbook.close()
                    page.screenshot(path=str(output / f"{name}.png"), full_page=True)

                page.locator("#execute-approved-button").click()
                expect(page.locator("#run-status")).to_have_text("OK：全ケース成功", timeout=120000)
                download_result("success", "OK")
                api.fault = "bad_datetime"
                page.locator("#run-button").click()
                expect(page.locator("#run-status")).to_contain_text("ケース準備完了", timeout=120000)
                page.locator("#execute-approved-button").click()
                expect(page.locator("#run-status")).to_have_text("NG：1件以上失敗", timeout=120000)
                download_result("detected-invalid-datetime", "NG")
                api.fault = "none"
                page.locator("#rerun-failed-button").click()
                expect(page.locator("#run-status")).to_have_text("OK：全ケース成功", timeout=120000)
                download_result("recovered", "OK")
                assert not errors, errors
            finally:
                (output / "page.txt").write_text(page.locator("body").inner_text(), encoding="utf-8")
                page.screenshot(path=str(output / "final.png"), full_page=True)
                browser.close()
    finally:
        for server in (api, host):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=5)
