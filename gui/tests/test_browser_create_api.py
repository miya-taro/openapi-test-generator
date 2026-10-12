"""Create a login contract from an empty UI, then save nested field definitions."""
import json
import os
import shutil
import threading
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1', reason='requires built UI and Chromium')
def test_create_login_in_browser(tmp_path, monkeypatch):
    from gui import web_server
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).parents[2]
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path / 'data' if name == 'DATA' else tmp_path / 'data' / name.lower()
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path / 'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root / 'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            try:
                page = browser.new_page()
                page.add_init_script('window.showSaveFilePicker = undefined')
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                page.locator('#new-api-name').fill('login')
                page.locator('#new-api-path').fill('/v1/auth/login')
                page.locator('#new-api-statuses').fill('200,400,401')
                page.locator('#new-api-create').click()
                expect(page.locator('#contract-editor-status')).to_contain_text('下書き')
                expect(page.locator('#contract-operation')).to_have_value('login')
                for side, names in [('request', ['username', 'password']), ('response', ['id', 'created_datetime'])]:
                    builder = page.locator(f'#contract-{side}-schema-builder')
                    for name in names:
                        builder.locator('[data-role="add-property"]').first.click()
                        prop = builder.locator('.schema-node-property').last
                        prop.locator('[data-role="property-name"]').fill(name)
                        prop.locator('[data-role="schema-type"]').select_option('string')
                        prop.get_by_label('必須', exact=True).check()
                        if name == 'created_datetime':
                            prop.get_by_label('形式', exact=True).select_option('date-time')
                page.locator('#contract-save-button').click()
                expect(page.locator('#contract-editor-status')).to_contain_text('試験対象に設定しました')
                saved = Path(page.locator('#openapi-path').input_value())
                doc = json.loads(saved.read_text(encoding='utf-8'))
                op = doc['paths']['/v1/auth/login']['post']
                assert set(op['requestBody']['content']['application/json']['schema']['required']) == {'username', 'password'}
                response = op['responses']['200']['content']['application/json']['schema']
                assert response['properties']['created_datetime']['format'] == 'date-time'
                assert set(response['required']) == {'id', 'created_datetime'}
                assert set(op['responses']) == {'200', '400', '401'}
                assert page.locator('#auth-login-op option[value="login"]').count() == 1
                # Duplicate registration must leave the saved contract unchanged.
                page.locator('[data-step="target"]').click()
                page.locator('#new-api-append').check()
                page.locator('#new-api-create').click()
                expect(page.locator('#new-api-message')).to_contain_text('登録済み')
                assert json.loads(saved.read_text(encoding='utf-8')) == doc
            finally:
                browser.close()
    finally:
        host.shutdown()
        host.server_close()
        thread.join(timeout=5)
