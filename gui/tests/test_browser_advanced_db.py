"""UI forms -> persisted plan -> native pytest -> actual DB -> evidence download."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INTEGRATION_DB_CONFIG') or not os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG'), reason='requires browser and dedicated PostgreSQL/InfluxDB')
@pytest.mark.parametrize('mode', ['rules', 'bulk', 'delete'])
def test_advanced_forms(tmp_path, monkeypatch, mode):
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server
    from docs.advanced_db_lab import AdvancedDatabaseLab, definitions

    root = Path(__file__).parents[2]
    config = {'postgres': json.loads(os.environ['OTG_INTEGRATION_DB_CONFIG']), 'influxdb': json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG'])}
    lab = AdvancedDatabaseLab(config)
    monkeypatch.setenv('TEST_AUTH_HEADER_NAME', 'auth-key')
    monkeypatch.setenv('TEST_AUTH_HEADER_VALUE', lab.token)
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path / 'evidence'))) / ('advanced-' + mode)
    output.mkdir(parents=True, exist_ok=True)
    api, scale, _, bulk = definitions(lab)
    spec = tmp_path / 'api.json'; spec.write_text(json.dumps(api))
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path / name.lower(); path.mkdir(); monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path / 'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root / 'gui-tauri/dist'))
    thread = threading.Thread(target=host.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=shutil.which('chromium'), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1050}, accept_downloads=True)
            page.set_default_timeout(15000)
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            def field(panel, key): return panel.locator(f'[data-advanced="{key}"]')
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(spec)
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(4)
                page.locator('#base-url').fill(lab.url)
                page.locator('#output-dir').fill(str(tmp_path / 'results'))
                page.locator('#pg-enabled').check()
                for key, value in lab.config['postgres'].items(): page.locator(f'#pg-{key}').fill(str(value))
                page.locator('#influx-enabled').check()
                for key, value in lab.config['influxdb'].items(): page.locator(f'#influx-{key}').fill(str(value))
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbsetup-display').click()
                if mode == 'rules':
                    ddl = page.locator('#db-ddl-catalog'); ddl.locator(':scope > summary').click()
                    ddl.locator('textarea').fill(f'CREATE TABLE {lab.records} (id integer PRIMARY KEY, amount numeric(15,3)); SELECT pg_sleep(100);')
                    ddl.locator('[data-ddl-import]').click()
                    expect(ddl.locator('[data-ddl-status]')).to_contain_text('1テーブル')
                    expect(ddl.locator('[data-ddl-result]')).to_contain_text('実行しません')
                    page.locator('#dbscenario-editor-operation').select_option('scale')
                    page.locator('#dbscenario-editor-mode').select_option('expectation_rules')
                    panel = page.locator('#dbscenario-rules-panel')
                    field(panel, 'body').fill(json.dumps(scale['request']['body']))
                    panel.get_by_role('button', name='処理を追加', exact=True).click()
                    field(panel, 'name').fill('scaled')
                    field(panel, 'kind').select_option('value')
                    field(panel, 'operation').select_option('mul')
                    field(panel, 'arg1').fill('body.value')
                    field(panel, 'arg2-kind').select_option('literal'); field(panel, 'arg2').fill('10')
                    panel.get_by_role('button', name='照合先を追加', exact=True).click()
                    field(panel, 'source').select_option('db')
                    field(panel, 'table').fill(lab.records)
                    expect(field(panel, 'table')).to_have_attribute('list', 'db-catalog-tables')
                    field(panel, 'columns').fill('amount')
                    field(panel, 'value-path').fill('0.amount')
                    panel.get_by_role('button', name='検索条件を追加', exact=True).click()
                    field(panel, 'column').fill('id'); field(panel, 'value').fill('body.id')
                    field(panel, 'expected').fill('steps.scaled')
                else:
                    page.locator('#dbscenario-editor-operation').select_option('bulkDelete' if mode == 'delete' else 'bulkUpdate')
                    page.locator('#dbscenario-editor-mode').select_option('influx_bulk')
                    panel = page.locator('#dbscenario-bulk-panel')
                    field(panel, 'measurement').fill('readings')
                    field(panel, 'body').fill(json.dumps(bulk['request']['body']))
                    field(panel, 'status').fill('204')
                    for name in ['scope', 'target']:
                        for key, value in bulk['influx_mutation'][name].items(): field(panel, name + '-' + key).fill(json.dumps(value) if key == 'tags' else value)
                    if mode == 'delete': field(panel, 'action').select_option('delete')
                    else:
                        panel.get_by_role('button', name='変更するフィールドを追加', exact=True).click()
                        field(panel, 'name').fill('value'); field(panel, 'operation').select_option('mul')
                        field(panel, 'arg1').fill('point.value'); field(panel, 'arg2').fill('body.factor')
                page.screenshot(path=str(output / 'settings.png'), full_page=True)
                page.locator('#dbscenario-editor-add-scenario').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('1件の対応を追加')
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                for fault in [None, 'wrong-scale' if mode == 'rules' else 'guard']:
                    lab.reset(); lab.fault = fault; before = len(lab.calls)
                    page.locator('#dbscenario-run-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました', timeout=120000)
                    assert len(lab.calls) == before
                    review = page.locator('#dbscenario-case-review-panel')
                    expect(review).to_contain_text('expectationRules' if mode == 'rules' else 'influxMutation')
                    if fault is None:
                        review.get_by_role('button', name='レビュー済みにする', exact=True).click()
                        review.get_by_role('button', name='承認する', exact=True).click()
                    page.locator('#dbscenario-execute-approved-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('NG' if fault else 'すべてのDB確認に成功', timeout=120000)
                    with page.expect_download() as download: page.locator('#dbscenario-open-result-button').click()
                    destination = output / f'{fault or "success"}.xlsx'; download.value.save_as(destination)
                    workbook = load_workbook(destination, read_only=True)
                    sheet = workbook['期待値ルール照合' if mode == 'rules' else 'InfluxDB一括照合']
                    assert any(('NG' if fault else 'OK') in row for row in sheet.values)
                    workbook.close()
                assert not errors, errors
            finally:
                (output / 'page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                page.screenshot(path=str(output / 'result.png'), full_page=True)
                browser.close()
    finally:
        host.shutdown(); host.server_close(); thread.join(timeout=5); lab.close()
