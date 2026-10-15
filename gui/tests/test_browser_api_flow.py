"""Create an API-only flow in Chromium, save, review and execute via pytest."""
import json
import os
from pathlib import Path
import shutil
import sys
import threading

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1', reason='requires built UI and Chromium')
def test_browser_authored_flow(tmp_path, monkeypatch, httpserver):
    from playwright.sync_api import sync_playwright, expect
    from werkzeug.wrappers import Response
    from gui import web_server
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            assert request.json == {'value': 42}
            payload = {'id': 7}
        elif request.method == 'GET':
            payload = {'state': 'running' if calls.count('GET') == 1 else 'done', 'value': 42}
        else:
            payload = {}
        return Response(json.dumps(payload), content_type='application/json')
    httpserver.expect_request('/jobs', method='POST').respond_with_handler(handler)
    httpserver.expect_request('/jobs/7', method='GET').respond_with_handler(handler)
    httpserver.expect_request('/jobs/7', method='DELETE').respond_with_handler(handler)
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path / name; path.mkdir(); monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path / 'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(ROOT / 'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.add_init_script('window.showSaveFilePicker = undefined')
            page.set_default_timeout(15000)
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                with page.expect_file_chooser() as chooser:
                    page.locator('#browse-openapi').click()
                chooser.value.set_files(ROOT / 'examples/api-flow/openapi.json')
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(3)
                page.locator('#base-url').fill(httpserver.url_for('/').rstrip('/'))
                page.locator('#output-dir').fill(str(tmp_path / 'results'))
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbscenario-editor-operation').select_option('get')
                page.locator('#dbscenario-editor-name').fill('API連続実行')
                page.get_by_role('button', name='DB照合なしのAPI試験を追加', exact=True).click()
                panel = page.locator('.api-flow-editor')
                panel.locator('summary').click()
                before = panel.locator(':scope > fieldset').filter(has=page.locator('legend', has_text='前処理API'))
                before.get_by_role('button', name='API手順を追加', exact=True).click()
                step = before.locator(':scope > fieldset')
                step.get_by_label('手順名（英数字、例 create）', exact=True).fill('create')
                step.get_by_label('呼び出すAPI', exact=True).select_option('create')
                row = step.locator('fieldset').filter(has=page.locator('legend', has_text='リクエストボディ')).locator('.api-flow-value-row')
                row.get_by_label('送信', exact=True).check()
                row.get_by_label('型', exact=True).select_option('number')
                row.get_by_label('値／手順名.レスポンス項目（例 create.id）', exact=True).fill('42')
                cleanup = panel.locator(':scope > fieldset').filter(has=page.locator('legend', has_text='後片付けAPI'))
                cleanup.get_by_role('button', name='API手順を追加', exact=True).click()
                deletion = cleanup.locator(':scope > fieldset')
                deletion.get_by_label('手順名（英数字、例 create）', exact=True).fill('delete')
                deletion.get_by_label('呼び出すAPI', exact=True).select_option('delete')
                def set_id(scope):
                    row = scope.locator('fieldset').filter(has=page.locator('legend', has_text='パスの値')).locator('.api-flow-value-row')
                    row.get_by_label('送信', exact=True).check()
                    row.get_by_label('値の指定', exact=True).select_option('step')
                    row.get_by_label('引き継ぐレスポンス項目', exact=True).select_option('create.id')
                set_id(deletion)
                # The main request editor is the only direct div under the panel.
                set_id(panel.locator(':scope > div'))
                wait = panel.locator(':scope > fieldset').filter(has=page.locator(':scope > legend', has_text='非同期処理'))
                wait.get_by_label('完了するまで繰り返し確認する', exact=True).check()
                wait.get_by_label('完了を確認する項目', exact=True).select_option('state')
                wait.get_by_label('完了時の値（例 done）', exact=True).fill('done')
                wait.get_by_label('確認間隔（秒）', exact=True).fill('45')
                expect(panel.locator('[role="status"]')).to_contain_text('確認間隔')
                wait.get_by_label('確認間隔（秒）', exact=True).fill('0.1')
                page.set_viewport_size({'width': 1000, 'height': 1000})
                picker = panel.locator(':scope > div').get_by_label('引き継ぐレスポンス項目', exact=True)
                picker.scroll_into_view_if_needed()
                box = picker.bounding_box()
                assert box and box['x'] >= 0 and box['x'] + box['width'] <= 1000
                page.screenshot(path=str(tmp_path / 'flow-picker.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                panel.get_by_role('button', name='連続実行の設定を反映', exact=True).click()
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                page.locator('#dbscenario-run-button').click()
                expect(page.locator('#dbscenario-status')).to_contain_text('実行前の確認を準備しました', timeout=60000)
                assert not calls
                review = page.locator('#dbscenario-case-review-list')
                review.get_by_role('button', name='レビュー済みにする', exact=True).click()
                review.get_by_role('button', name='承認する', exact=True).click()
                page.locator('#dbscenario-execute-approved-button').click()
                expect(page.locator('#dbscenario-status')).to_contain_text('OK', timeout=60000)
                assert calls == ['POST', 'GET', 'GET', 'DELETE']
                assert not errors, errors
            finally:
                page.screenshot(path=str(tmp_path / 'api-flow.png'), full_page=True)
                (tmp_path / 'browser.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                browser.close()
    finally:
        host.shutdown(); host.server_close(); thread.join(timeout=5)
