"""Actual browser -> saved mapping -> reviewed execution -> PostgreSQL -> Excel."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires Chromium and dedicated PostgreSQL')
def test_browser_pwrco_suite_workflow(tmp_path, monkeypatch):
    from docs.pwrco_fixture_api import PwrcoFixture
    from docs.pwrco_suite import build_suite
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server
    root = Path(__file__).parents[2]
    config = json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG'])
    api = PwrcoFixture(config)
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path/'evidence'))) / 'pwrco'
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
                chooser.value.set_files(root/'examples/pwrco/openapi.json')
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('#base-url').fill(api.url)
                page.locator('#output-dir').fill(str(tmp_path/'results'))
                page.locator('#pg-enabled').check()
                for key in ['host','port','dbname','user','password']:
                    page.locator(f'#pg-{key}').fill(str(config[key]))
                page.locator('[data-page="db-scenario"]').click()
                scenario=tmp_path/'pwrco.json'
                scenario.write_text(json.dumps(build_suite('2026-10-12T00:00:00+09:00',api.table,api.site_table)))
                with page.expect_file_chooser() as chooser: page.locator('#dbscenario-browse').click()
                chooser.value.set_files(scenario)
                for fault in [None]:
                    api.fault=fault
                    before=len(api.calls)
                    page.locator('#dbscenario-run-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました',timeout=120000)
                    assert len(api.calls)==before
                    review=page.locator('#dbscenario-case-review-panel')
                    expect(review).to_contain_text('dbInsertCheck')
                    if not fault:
                        for index in range(38):
                            card=review.locator('article').nth(index)
                            card.get_by_role('button',name='レビュー済みにする',exact=True).click()
                            card.get_by_role('button',name='承認する',exact=True).click()
                            expect(card).to_contain_text('承認済み')
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
                assert len(api.calls)==38
                assert not errors,errors
            finally:
                (output/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                page.screenshot(path=str(output/'result.png'),full_page=True)
                browser.close()
    finally:
        host.shutdown();host.server_close();thread.join(timeout=5);api.close()
