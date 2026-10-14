"""Actual browser: InfluxDB mapping generation and saved configuration round trip."""
import json
import os
from pathlib import Path
import shutil
import threading

import pytest
import yaml


@pytest.mark.skipif(os.environ.get("OTG_BROWSER_TEST") != "1", reason="requires built UI and Chromium")
def test_influx_configuration_in_browser(tmp_path, monkeypatch):
    from gui import web_server
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).parents[2]
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path / 'evidence'))) / 'influx'
    output.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path / 'app'
    tmp.mkdir()
    for name in ('DATA','IMPORTS','SAVED','OUTPUT','TEMP'):
        path=tmp/name.lower();path.mkdir();monkeypatch.setattr(web_server,name,path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp/'settings.json')
    server=web_server.WebServer(('127.0.0.1',0),web_server.WebState(root/'gui-tauri/dist'))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome'),headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1050},accept_downloads=True)
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.locator('[data-step="target"]').click()
            with page.expect_file_chooser() as chooser:page.locator('#browse-openapi').click()
            chooser.value.set_files(root/'examples/measure-get-openapi.json')
            expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
            page.locator('[data-page="db-scenario"]').click()
            page.locator('#dbsetup-display').click()  # Advanced full-form editing remains available.
            expect(page.locator('#dbscenario-editor-operation option')).to_have_count(2)
            operation=page.locator('#dbscenario-editor-operation option').nth(1).get_attribute('value')
            page.locator('#dbscenario-editor-operation').select_option(operation)
            page.locator('#dbscenario-editor-engine').select_option('influxdb')
            page.locator('#dbscenario-editor-table').fill('measure')
            page.locator('#dbscenario-editor-name').fill('InfluxDB期間内のデータを照合')
            body={'site_id':1,'location_id':'B','start':'2026-01-01T00:00:01Z','end':'2026-01-01T00:00:03Z','items':['a','b']}
            columns={'site_id':'site','location_id':'location','start':'time','end':'time','items':'item'}
            for name,value in body.items():
                row=page.locator(f'#dbscenario-editor-read-filters tr[data-parameter-name="{name}"]')
                row.locator('[data-request-value]').fill(json.dumps(value))
                row.locator('[data-db-column]').fill(columns[name])
                if name=='start':row.locator('select').first.select_option('>=')
                if name=='end':row.locator('select').first.select_option('<=')
                if name=='items':row.locator('select').first.select_option('in')
                if name in ['site_id','location_id']:
                    row.locator('select').first.select_option('=')
                    row.locator('[data-or-group]').select_option(index=1)
            for name in ['time','item','value']:
                page.locator(f'#dbscenario-editor-read-mappings tr[data-response-path="{name}"] [data-db-column]').fill(name)
            page.locator('#dbscenario-editor-expand-combinations').check()
            page.locator('#dbscenario-editor-add-scenario').click()
            expect(page.locator('#dbscenario-editor-status')).to_contain_text('18件の対応を追加')
            page.screenshot(path=str(output/'get-mapping.png'),full_page=True)
            page.locator('#dbscenario-editor-save').click()
            expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
            saved_path=Path(page.locator('#dbscenario-path').input_value())
            target=output/'db-checks.yaml';target.write_text(saved_path.read_text())
            saved=yaml.safe_load(target.read_text())['scenarios']['list']
            assert len(saved)==18
            assert all(x['db_response_check']['engine']=='influxdb' for x in saved)
            expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
            # Add a cross-DB mapping through the visible UI and verify saved provenance.
            page.locator('#dbscenario-editor-expand-combinations').uncheck()
            page.locator('#dbscenario-editor-name').fill('locationからPostgreSQLを参照してInfluxDBと照合')
            page.locator('#dbscenario-editor-read-filters tr[data-parameter-name="site_id"] [data-request-value]').fill('')
            lookup_row = page.locator('#dbscenario-editor-read-filters tr[data-parameter-name="location_id"]')
            lookup_row.locator('[data-db-column]').fill('site')
            lookup_row.locator('[data-or-group]').select_option('')
            lookup_row.locator('[data-lookup-enabled]').check()
            for key, value in {'table': 't_site', 'match_column': 'location_id', 'value_column': 'site_id'}.items():
                lookup_row.locator(f'[data-lookup-field="{key}"]').fill(value)
            lookup_row.locator('[data-lookup-field="cardinality"]').select_option('many')
            lookup_row.locator('[data-lookup-field="value_type"]').select_option('integer')
            lookup_row.locator('[data-lookup-field="on_empty"]').select_option('status')
            lookup_row.locator('[data-lookup-field="empty_status"]').fill('400')
            expect(lookup_row.locator('select[aria-label="DBとの比較条件"]')).to_have_value('in')
            page.screenshot(path=str(output/'lookup-mapping.png'), full_page=True)
            page.locator('#dbscenario-editor-add-scenario').click()
            expect(page.locator('#dbscenario-editor-status')).to_contain_text('1件の対応を追加')
            page.locator('#dbscenario-editor-save').click()
            expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
            lookup_saved = yaml.safe_load(Path(page.locator('#dbscenario-path').input_value()).read_text())['scenarios']['list'][-1]
            assert lookup_saved['request']['body']['location_id'] == 'B' and 'site_id' not in lookup_saved['request']['body']
            reference = next(f for f in lookup_saved['db_response_check']['filters'] if f['parameter'] == 'location_id')
            assert reference['lookup'] == {'engine': 'postgres', 'table': 't_site', 'match_column': 'location_id',
                                           'value_column': 'site_id', 'cardinality': 'many', 'value_type': 'integer',
                                           'on_empty': 'status', 'empty_status': 400}
            page.locator('[data-step="review"]').click()
            page.locator('#contract-operation').select_option(operation)
            expect(page.locator('#contract-editor-status')).to_contain_text('読み込みました')
            page.get_by_text('自動生成する異常系でDBが変わらないことを確認',exact=True).click()
            page.locator('#contract-add-error-db-scope').click()
            scope=page.locator('.error-db-scope')
            scope.locator('[data-key="engine"]').select_option('influxdb')
            for key,value in {'table':'measure','columns':'time, location, item, value','where':'{}','time_start':'2026-01-01T00:00:00Z','time_end':'2026-01-01T00:00:04Z'}.items():scope.locator(f'[data-key="{key}"]').fill(value)
            page.screenshot(path=str(output/'error-scope.png'),full_page=True)
            with page.expect_download() as download:page.locator('#contract-save-button').click()
            target=output/'saved-openapi.json';download.value.save_as(target)
            saved=json.loads(target.read_text());scope=next(iter(saved['paths'].values()))['get']['x-otg-error-db-unchanged'][0]
            assert scope['engine']=='influxdb' and scope['time_end']=='2026-01-01T00:00:04Z'
            expect(page.locator('#contract-editor-status')).to_contain_text('試験対象に設定しました')
            expect(page.locator('.error-db-scope [data-key="engine"]')).to_have_value('influxdb')
            assert not errors,errors
            browser.close()
            print('Actual Chromium: InfluxDB GET mappings -> 18 cases -> saved YAML; error scope -> OpenAPI save/reload passed')
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
