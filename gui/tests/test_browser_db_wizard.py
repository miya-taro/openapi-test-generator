"""Guided GET setup through actual Chromium, HTTP, PostgreSQL and Excel evidence."""
import json
import os
from pathlib import Path
import shutil
import threading
from contextlib import closing

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires Chromium and dedicated PostgreSQL')
def test_guided_get_setup_and_execution(tmp_path, monkeypatch):
    import psycopg2
    from psycopg2 import sql
    from docs.rule_fixture_api import RuleFixture, contract
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server

    root = Path(__file__).parents[2]
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    api = RuleFixture('postgres', config)
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path/'evidence'))) / 'guided-get'
    output.mkdir(parents=True, exist_ok=True)
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path/name.lower(); path.mkdir(); monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path/'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root/'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
    try:
        with closing(psycopg2.connect(**config)) as conn, conn.cursor() as cur:
            for hour, value in [(-1, 5), (0, 10), (12, 20), (24, 30)]:
                cur.execute(sql.SQL("INSERT INTO {} (site,datetime,value) VALUES ('test','2026-01-01T00:00:00Z'::timestamptz + %s * interval '1 hour',%s)").format(sql.Identifier(api.table)), (hour, value))
            cur.execute(sql.SQL("INSERT INTO {} (site,datetime,value) VALUES ('other','2026-01-01T12:00:00Z',40)").format(sql.Identifier(api.table)))
            conn.commit()
        spec = contract()
        schema = spec['paths']['/range']['get']['requestBody']['content']['application/json']['schema']
        schema['properties'] = {key: schema['properties'][key] for key in ('site', 'start', 'end')}
        schema['required'] = ['site', 'start', 'end']
        source = tmp_path/'openapi.json'; source.write_text(json.dumps(spec))
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium'), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1440, 'height':1050}, accept_downloads=True)
            page.set_default_timeout(15000)
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(source)
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('#base-url').fill(api.url)
                page.locator('#output-dir').fill(str(tmp_path/'results'))
                page.locator('#pg-enabled').check()
                for key in ('host', 'port', 'dbname', 'user', 'password'):
                    page.locator(f'#pg-{key}').fill(str(config[key]))
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbscenario-editor-operation').select_option('ruleRead')
                expect(page.locator('#dbscenario-editor-table')).not_to_be_visible()
                page.locator('#dbsetup-next').click()
                values = {'site':'test', 'start':'2026-01-01T00:00:00Z', 'end':'2026-01-02T00:00:00Z'}
                for key, value in values.items():
                    row = page.locator(f'#dbscenario-editor-read-filters tr[data-parameter-name="{key}"]')
                    row.locator('[data-request-value]').fill(json.dumps(value))
                    expect(row.locator('[data-db-column]')).not_to_be_visible()
                page.locator('#dbscenario-setup').evaluate("node => node.scrollIntoView({block:'start'})")
                page.screenshot(path=str(output/'2-request.png'))
                page.locator('#dbsetup-back').click()
                page.locator('#dbscenario-editor-name').fill('期間内の値をDBと照合')
                page.locator('#dbsetup-next').click()
                expect(page.locator('[data-parameter-name="site"] [data-request-value]')).to_have_value('"test"')
                page.locator('#dbsetup-next').click()
                expect(page.locator('#dbscenario-editor-table')).to_be_visible()
                page.locator('#dbsetup-next').click()
                expect(page.locator('#dbscenario-setup')).to_have_attribute('data-stage', '3')
                expect(page.locator('#dbsetup-error')).to_be_visible()
                page.locator('#dbscenario-editor-table').fill(api.table)
                for key, column, op in [('site', 'site', '='), ('start', 'datetime', '>='), ('end', 'datetime', '<')]:
                    row = page.locator(f'#dbscenario-editor-read-filters tr[data-parameter-name="{key}"]')
                    expect(row.locator('[data-request-value]')).not_to_be_visible()
                    row.locator('[data-db-column]').fill(column)
                    row.locator('select[aria-label="DBとの比較条件"]').select_option(op)
                page.locator('#dbscenario-editor-read-mappings [data-db-column]').fill('value')
                page.locator('#dbscenario-setup').evaluate("node => node.scrollIntoView({block:'start'})")
                page.screenshot(path=str(output/'3-db.png'))
                page.locator('#dbsetup-next').click()
                expect(page.locator('#dbsetup-preview')).to_contain_text('追加する試験：1件')
                expect(page.locator('#dbsetup-preview')).to_contain_text('期待ステータス：200')
                request = page.locator('#dbsetup-preview article details').first.locator('pre')
                assert json.loads(request.inner_text())['body'] == values
                assert not api.calls  # Setup and preview never execute the target API.
                page.locator('#dbscenario-setup').evaluate("node => node.scrollIntoView({block:'start'})")
                page.screenshot(path=str(output/'4-preview.png'))
                page.locator('#dbscenario-editor-add-scenario').click()
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                saved_path = page.locator('#dbscenario-path').input_value()
                # The saved mapping must survive a real application restart.
                page.context.close()
                host.shutdown(); host.server_close(); thread.join(timeout=5)
                host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root/'gui-tauri/dist'))
                thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
                page = browser.new_page(viewport={'width':1440, 'height':1050}, accept_downloads=True)
                page.set_default_timeout(15000)
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                expect(page.locator('#base-url')).to_have_value(api.url)
                expect(page.locator('#pg-enabled')).to_be_checked()
                expect(page.locator('#pg-password')).to_have_value('')
                page.locator('#pg-password').fill(str(config['password']))
                page.locator('[data-page="db-scenario"]').click()
                expect(page.locator('#dbscenario-path')).to_have_value(saved_path)
                expect(page.locator('#dbscenario-editor-scenario-list')).to_contain_text('期間内の値をDBと照合')
                for fault in [None, 'wrong-value']:
                    api.fault = fault
                    before = len(api.calls)
                    page.locator('#dbscenario-run-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました', timeout=120000)
                    assert len(api.calls) == before
                    review = page.locator('#dbscenario-case-review-panel')
                    if not fault:
                        review.get_by_role('button', name='レビュー済みにする', exact=True).click()
                        review.get_by_role('button', name='承認する', exact=True).click()
                    page.locator('#dbscenario-execute-approved-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('NG' if fault else 'すべてのDB確認に成功', timeout=120000)
                    with page.expect_download() as download: page.locator('#dbscenario-open-result-button').click()
                    destination = output/f'{fault or "success"}.xlsx'; download.value.save_as(destination)
                    workbook = load_workbook(destination, read_only=True)
                    assert any(('NG' if fault else 'OK') in row for sheet in workbook for row in sheet.values)
                    workbook.close()
                assert api.calls == [values, values]
                assert not errors, errors
            finally:
                page.screenshot(path=str(output/'result.png'))
                (output/'page.txt').write_text(page.locator('body').inner_text())
                browser.close()
    finally:
        host.shutdown(); host.server_close(); thread.join(timeout=5); api.close()
