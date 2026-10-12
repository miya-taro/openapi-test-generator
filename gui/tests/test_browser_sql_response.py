"""Actual browser -> saved mapping -> reviewed execution -> PostgreSQL -> Excel."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires Chromium and dedicated PostgreSQL')
def test_browser_sql_response_workflow(tmp_path, monkeypatch):
    from docs.plan_get_fixture_api import PlanGetFixture
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server
    root = Path(__file__).parents[2]
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    api = PlanGetFixture(config)
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path/'evidence'))) / 'sql-response'
    output.mkdir(parents=True, exist_ok=True)
    for name in ('DATA','IMPORTS','SAVED','OUTPUT','TEMP'):
        path=tmp_path/name.lower();path.mkdir();monkeypatch.setattr(web_server,name,path)
    monkeypatch.setattr(web_server,'SETTINGS',tmp_path/'settings.json')
    host = web_server.WebServer(('127.0.0.1',0),web_server.WebState(root/'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
            page.set_default_timeout(15000)
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(root/'examples/plan-get/openapi.json')
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('#base-url').fill(api.url)
                page.locator('#output-dir').fill(str(tmp_path/'results'))
                page.locator('#pg-enabled').check()
                for key in ['host','port','dbname','user','password']:
                    page.locator(f'#pg-{key}').fill(str(config[key]))
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbscenario-editor-operation').select_option('getPlanControl')
                page.locator('#dbscenario-editor-mode').select_option('sql_response')
                page.get_by_role('button',name='計画取得の対応例を設定',exact=True).click()
                panel=page.locator('#dbscenario-sql-panel')
                panel.locator('[data-sql-field="body"]').fill((root/'examples/plan-get/request.json').read_text())
                panel.locator('[data-sql-field="sql"]').fill(api.definition()['db_sql_response_check']['sql'])
                page.screenshot(path=str(output/'mapping.png'),full_page=True)
                page.locator('#dbscenario-editor-add-scenario').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('1件の対応を追加')
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                for fault in [None,'history']:
                    api.fault=fault
                    before=len(api.calls)
                    page.locator('#dbscenario-run-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました',timeout=120000)
                    assert len(api.calls)==before
                    review=page.locator('#dbscenario-case-review-panel')
                    expect(review).to_contain_text('dbSqlResponseCheck')
                    if not fault:
                        review.get_by_role('button',name='レビュー済みにする',exact=True).click()
                        review.get_by_role('button',name='承認する',exact=True).click()
                    page.locator('#dbscenario-execute-approved-button').click()
                    expected='1件以上のDB確認で不一致' if fault else 'すべてのDB確認に成功'
                    if fault:
                        expect(page.locator('#dbscenario-status')).to_contain_text('NG',timeout=120000)
                    else:
                        expect(page.locator('#dbscenario-status')).to_contain_text(expected,timeout=120000)
                    with page.expect_download() as download: page.locator('#dbscenario-open-result-button').click()
                    destination=output/f'{fault or "success"}.xlsx';download.value.save_as(destination)
                    workbook=load_workbook(destination,read_only=True)
                    assert any(('NG' if fault else 'OK') in row for sheet in workbook for row in sheet.values)
                    workbook.close()
                assert not errors,errors
            finally:
                (output/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                page.screenshot(path=str(output/'result.png'),full_page=True)
                browser.close()
    finally:
        host.shutdown();host.server_close();thread.join(timeout=5);api.close()
