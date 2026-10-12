"""UI login configuration -> real auth-key request and isolated auth probes."""
import json
import os
import shutil
import threading
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1', reason='requires built UI and Chromium')
def test_browser_login_auth_key(tmp_path,monkeypatch):
    from docs.login_fixture_api import LoginFixture, USERNAME, PASSWORD, TOKEN
    from gui import web_server
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    root=Path(__file__).parents[2]
    for name in ('DATA','IMPORTS','SAVED','OUTPUT','TEMP'):
        path=tmp_path/name.lower();path.mkdir();monkeypatch.setattr(web_server,name,path)
    monkeypatch.setattr(web_server,'SETTINGS',tmp_path/'settings.json')
    api=LoginFixture()
    host=web_server.WebServer(('127.0.0.1',0),web_server.WebState(root/'gui-tauri/dist'))
    thread=threading.Thread(target=host.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            try:
                page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
                page.set_default_timeout(20000)
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser:page.locator('#browse-openapi').click()
                chooser.value.set_files(root/'examples/login/openapi.json')
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(2)
                page.locator('#base-url').fill(api.url)
                page.locator('#output-dir').fill(str(tmp_path/'results'))
                page.locator('#ops-select-none').click()
                page.locator('#operations-list input[data-op-id="protected"]').check()
                page.locator('[data-step="run"]').click()
                page.locator('#advanced-settings > summary').click()
                page.locator('#auth-enabled').check()
                page.locator('#auth-login-op').select_option('login')
                page.locator('#auth-body').fill(json.dumps({'username':USERNAME,'password':PASSWORD}))
                page.locator('#auth-token-path').fill('id')
                page.locator('#auth-header-name').fill('auth-key')
                page.locator('#auth-header-format').fill('{token}')
                page.locator('#run-button').click()
                expect(page.locator('#run-status')).to_contain_text('ケース準備完了',timeout=120000)
                cards=page.locator('#case-review-list article')
                expect(cards).to_have_count(3)
                for index in range(3):
                    cards.nth(index).get_by_role('button',name='レビュー済みにする',exact=True).click()
                    cards.nth(index).get_by_role('button',name='承認する',exact=True).click()
                    expect(cards.nth(index)).to_contain_text('承認済み')
                page.locator('#execute-approved-button').click()
                expect(page.locator('#run-status')).to_have_text('OK：全ケース成功',timeout=120000)
                assert sum(c.get('authenticated') is True for c in api.calls)==1
                assert sum(c.get('authenticated') is False for c in api.calls)==2
                assert sum(c['path']=='/v1/auth/login' for c in api.calls)==1
                with page.expect_download() as download:page.locator('#open-result-button').click()
                path=tmp_path/'result.xlsx';download.value.save_as(path)
                book=load_workbook(path,read_only=True)
                cells='\n'.join(str(v) for sheet in book for row in sheet.values for v in row)
                book.close()
                assert PASSWORD not in cells and TOKEN not in cells
            finally:
                browser.close()
    finally:
        host.shutdown();host.server_close();thread.join(timeout=5);api.close()
