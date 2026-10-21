"""Usability regression: keyboard focus, recoverable edits, scoped choices and small screens."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1', reason='requires Chromium and built UI')
@pytest.mark.parametrize('width', [1280, 800])
def test_expectation_editor_usability(tmp_path, monkeypatch, width):
    from gui import web_server
    from playwright.sync_api import sync_playwright, expect
    root = Path(__file__).parents[2]
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path / name.lower(); path.mkdir(); monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path / 'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root / 'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
    spec = tmp_path / 'api.json'
    spec.write_text(json.dumps({'openapi': '3.1.0', 'info': {'title': 'Usability', 'version': '1'}, 'paths': {'/value': {'post': {
        'operationId': 'saveValue', 'requestBody': {'content': {'application/json': {'schema': {
            'type': 'object', 'properties': {'value': {'type': 'number'}}}}}}, 'responses': {'200': {'description': 'OK'}}}}}}))
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path/'evidence'))) / f'usability-{width}'; output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which('chromium'), args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': width, 'height': 900})
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def field(node, name): return node.locator(f'[data-advanced="{name}"]')
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(spec)
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbscenario-editor-operation').select_option('saveValue')
                page.locator('#dbscenario-editor-mode').select_option('expectation_rules')
                page.locator('#dbsetup-next').click()
                panel = page.locator('#dbscenario-rules-panel')
                field(panel, 'body').fill('{bad json')
                page.locator('#dbsetup-next').click()
                expect(field(panel, 'body')).to_be_focused()
                expect(field(panel, 'body')).to_have_attribute('aria-invalid', 'true')
                field(panel, 'body').fill('{"value": 2}')
                page.locator('#dbsetup-next').click()
                expect(page.locator('#dbsetup-heading')).to_contain_text('3.')
                panel.get_by_role('button', name='処理を追加', exact=True).click()
                step = panel.locator('[data-expected-step]')
                field(step, 'table').fill('readings'); field(step, 'columns').fill('value')
                field(step, 'kind').select_option('value')
                field(step, 'arg1').focus()
                expect(panel.locator('datalist option[value="body.value"]')).to_have_count(1)
                field(step, 'arg1').fill('body.value')
                field(step, 'kind').select_option('query')
                expect(field(step, 'table')).to_have_value('readings')
                field(step, 'kind').select_option('value')
                expect(field(step, 'arg1')).to_have_value('body.value')
                panel.get_by_role('button', name='照合先を追加', exact=True).click()
                field(panel, 'expected').fill('steps.mistake')
                page.locator('#dbsetup-next').click()
                expect(field(panel, 'expected')).to_be_focused()
                expect(page.locator('#dbsetup-error')).to_contain_text('処理「mistake」')
                field(panel, 'expected').fill('steps.step1')
                page.locator('#dbsetup-next').click()
                expect(page.locator('#dbsetup-heading')).to_contain_text('4.')
                expect(page.locator('#dbsetup-preview')).to_contain_text('1処理・1照合')
                page.locator('#dbsetup-back').click()
                expect(field(step, 'arg1')).to_have_value('body.value')
                # Visible controls fit the panel at both desktop and narrow window widths.
                controls = panel.locator('input:visible, select:visible, textarea:visible, button:visible')
                for control in controls.all():
                    box = control.bounding_box()
                    assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1, (control.get_attribute('aria-label'), box)
                field(panel, 'expected').scroll_into_view_if_needed()
                page.screenshot(path=str(output/'editor.png'))
                assert not errors, errors
            finally:
                (output/'page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                browser.close()
    finally:
        host.shutdown(); host.server_close(); thread.join(timeout=5)
