"""Actual form -> preview -> save/reload -> approval -> HTTP/DB -> Excel."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest
import yaml


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INTEGRATION_DB_CONFIG'), reason='requires Chromium and dedicated PostgreSQL')
@pytest.mark.parametrize('kind,count', [('boundary', 6), ('priority', 8), ('empty', 1), ('combinations', 16)])
def test_browser_rule_workflow(tmp_path, monkeypatch, kind, count):
    from docs.rule_fixture_api import RuleFixture, contract, rule_input, generate
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server
    root = Path(__file__).parents[2]
    api = RuleFixture('postgres', json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']))
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path/'evidence')))/('rules-'+kind)
    output.mkdir(parents=True, exist_ok=True)
    spec = tmp_path/'openapi.json'; spec.write_text(json.dumps(contract(kind)))
    # Load a reusable form template, then perform generation/save through actual controls.
    base = generate(rule_input(api, kind))[0]
    source = tmp_path/'template.yaml'; source.write_text(yaml.safe_dump({'scenarios': [base]}))
    for name in ('DATA','IMPORTS','SAVED','OUTPUT','TEMP'):
        path=tmp_path/name.lower(); path.mkdir(); monkeypatch.setattr(web_server,name,path)
    monkeypatch.setattr(web_server,'SETTINGS',tmp_path/'settings.json')
    host = web_server.WebServer(('127.0.0.1',0),web_server.WebState(root/'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever,daemon=True); thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium'),headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
            page.set_default_timeout(15000); page.add_init_script('window.showSaveFilePicker = undefined;')
            errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(spec)
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('#base-url').fill(api.url); page.locator('#output-dir').fill(str(tmp_path/'results'))
                page.locator('#pg-enabled').check()
                for key in ['host','port','dbname','user','password']:
                    page.locator(f'#pg-{key}').fill(str(api.config[key]))
                page.locator('[data-page="db-scenario"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#dbscenario-browse').click()
                chooser.value.set_files(source)
                page.get_by_role('button',name='選択したDB確認ファイルを編集用に読み込む',exact=True).click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('1件を編集用に読み込み')
                rules=page.locator('.rule-controls').first
                rules.locator('summary').first.click()
                rules.get_by_role('button',name='生成する試験を確認',exact=True).click()
                expect(rules.locator('[role="status"]')).to_contain_text(f'{count}件を生成')
                expect(rules.locator('.rule-preview li')).to_have_count(count)
                assert not api.calls
                rules.screenshot(path=str(output/'form.png'))
                rules.get_by_role('button',name='確認した試験を追加',exact=True).click()
                page.locator('.db-scenario-editor-list-item > button').first.click()  # remove base template
                expect(page.locator('.db-scenario-editor-list-item')).to_have_count(count)
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                for _ in range(count): page.locator('.db-scenario-editor-list-item > button').first.click()
                page.get_by_role('button',name='選択したDB確認ファイルを編集用に読み込む',exact=True).click()
                expect(page.locator('.db-scenario-editor-list-item')).to_have_count(count)
                restored=page.locator('.rule-controls').first; restored.locator('summary').first.click()
                expect(restored.get_by_label('試験ルール',exact=True)).to_have_value(kind)
                page.locator('#dbscenario-run-button').click()
                expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました',timeout=120000)
                assert not api.calls
                review=page.locator('#dbscenario-case-review-panel')
                expect(review).to_contain_text('ruleTest')
                for index in range(count):
                    card = review.locator('.case-review-card').nth(index)
                    card.get_by_role('button',name='レビュー済みにする',exact=True).click()
                    expect(card.locator('.case-review-status')).to_have_text('レビュー済み')
                    card.get_by_role('button',name='承認する',exact=True).click()
                    expect(card.locator('.case-review-status')).to_have_text('承認済み')
                page.locator('#dbscenario-execute-approved-button').click()
                expect(page.locator('#dbscenario-status')).to_contain_text('すべてのDB確認に成功',timeout=120000)
                assert len(api.calls)==count and api.rows('test')==[]
                with page.expect_download() as download: page.locator('#dbscenario-open-result-button').click()
                destination=output/'success.xlsx'; download.value.save_as(destination)
                workbook=load_workbook(destination,read_only=True)
                assert any('OK' in row for sheet in workbook for row in sheet.values)
                workbook.close()
                assert not errors,errors
            finally:
                (output/'page.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                page.screenshot(path=str(output/'result.png'),full_page=True); browser.close()
    finally:
        host.shutdown(); host.server_close(); thread.join(timeout=5); api.close()
