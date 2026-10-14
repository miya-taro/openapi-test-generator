"""Browser-only user workflow: configure POST mapping -> approve -> real DB -> download."""
import json
import os
from pathlib import Path
import shutil
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.skipif(os.environ.get('OTG_BROWSER_TEST') != '1' or not os.environ.get('OTG_INFLUX_INTEGRATION_CONFIG'), reason='requires browser and real InfluxDB')
@pytest.mark.parametrize('managed', [False, True])
def test_browser_influx_post_workflow(tmp_path, monkeypatch, managed):
    from influxdb import InfluxDBClient
    from playwright.sync_api import sync_playwright, expect
    from openpyxl import load_workbook
    from gui import web_server

    root = Path(__file__).parents[2]
    output = Path(os.environ.get('OTG_BROWSER_EVIDENCE_DIR', str(tmp_path / 'evidence'))) / ('influx-fixture' if managed else 'influx-mutation')
    output.mkdir(parents=True, exist_ok=True)
    config = {**json.loads(os.environ['OTG_INFLUX_INTEGRATION_CONFIG']), 'database': 'otg_browser_' + uuid.uuid4().hex[:12]}
    client = InfluxDBClient(**config)
    client.create_database(config['database'])
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            client.write_points([{'measurement': 'measure', 'time': body['time'], 'tags': {'item': body['item']}, 'fields': {'value': float(body['value'])}}])
            self.send_response(201)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
    api = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    for name in ('DATA', 'IMPORTS', 'SAVED', 'OUTPUT', 'TEMP'):
        path = tmp_path / name.lower(); path.mkdir(); monkeypatch.setattr(web_server, name, path)
    monkeypatch.setattr(web_server, 'SETTINGS', tmp_path / 'settings.json')
    host = web_server.WebServer(('127.0.0.1', 0), web_server.WebState(root / 'gui-tauri/dist'))
    servers = [api, host]
    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
    for thread in threads: thread.start()
    spec = tmp_path / 'api.json'
    request_schema = {'type': 'object', 'required': ['time', 'item', 'value'], 'properties': {
        'time': {'type': 'string', 'format': 'date-time'}, 'item': {'type': 'string'}, 'value': {'type': 'number'}}}
    response_schema = {'type': 'object', 'required': ['ok'], 'properties': {'ok': {'type': 'boolean'}}}
    operation = {
        'operationId': 'writeMeasure',
        'requestBody': {'content': {'application/json': {'schema': request_schema}}},
        'responses': {'201': {'description': 'Created', 'content': {'application/json': {'schema': response_schema}}}},
    }
    spec.write_text(json.dumps({'openapi': '3.1.0', 'paths': {'/measure': {'post': operation}}}))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('OTG_BROWSER_EXECUTABLE') or shutil.which('chromium') or shutil.which('google-chrome'), headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1050}, accept_downloads=True)
            page.set_default_timeout(15000)
            page.add_init_script('window.showSaveFilePicker = undefined;')
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            try:
                page.goto(f'http://127.0.0.1:{host.server_port}/')
                page.locator('[data-step="target"]').click()
                with page.expect_file_chooser() as chooser: page.locator('#browse-openapi').click()
                chooser.value.set_files(spec)
                expect(page.locator('#operations-list input[data-op-id]')).to_have_count(1)
                page.locator('#base-url').fill(f'http://127.0.0.1:{api.server_port}')
                page.locator('#output-dir').fill(str(tmp_path / 'results'))
                page.locator('#influx-enabled').check()
                for key, value in [('host', config['host']), ('port', config['port']), ('database', config['database'])]:
                    page.locator(f'#influx-{key}').fill(str(value))
                for key in ['username', 'password']:
                    if config.get(key): page.locator(f'#influx-{key}').fill(config[key])
                page.locator('[data-page="db-scenario"]').click()
                page.locator('#dbsetup-display').click()  # Advanced full-form editing remains available.
                page.locator('#dbscenario-editor-operation').select_option('writeMeasure')
                page.locator('#dbscenario-editor-engine').select_option('influxdb')
                page.locator('#dbscenario-editor-table').fill('measure')
                page.locator('#dbscenario-editor-influx-time').fill('2026-01-01T00:00:00Z')
                page.locator('#dbscenario-editor-influx-tags').fill('{"item":"a"}')
                for field, value in [('time', '2026-01-01T00:00:00Z'), ('item', 'a'), ('value', '2')]:
                    row = page.locator(f'#dbscenario-editor-write-mappings tr[data-field-path="{field}"]')
                    row.locator('[data-api-value]').fill(value)
                    if field == 'value': row.locator('[aria-label="DBカラム"]').fill('value')
                if managed: page.locator('#dbscenario-editor-influx-fixture').check()
                page.locator('#dbscenario-editor-add-scenario').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('1件の対応を追加')
                page.locator('#dbscenario-editor-save').click()
                expect(page.locator('#dbscenario-editor-status')).to_contain_text('保存しました')
                for cycle in range(2 if managed else 1):
                    page.locator('#dbscenario-run-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('確認を準備しました', timeout=120000)
                    assert len(calls) == cycle, 'Preparing must not execute the API'
                    review = page.locator('#dbscenario-case-review-panel')
                    expect(review).to_contain_text('influxMutation')
                    if cycle == 0:
                        review.get_by_role('button', name='レビュー済みにする', exact=True).click()
                        review.get_by_role('button', name='承認する', exact=True).click()
                    else:
                        expect(review).to_contain_text('承認済み')
                    page.locator('#dbscenario-execute-approved-button').click()
                    expect(page.locator('#dbscenario-status')).to_contain_text('すべてのDB確認に成功', timeout=120000)
                    assert len(calls) == cycle + 1
                    rows = list(client.query('SELECT * FROM measure').get_points())
                    if managed: assert rows == []
                    else: assert rows[0]['value'] == 2.0
                    with page.expect_download() as download: page.locator('#dbscenario-open-result-button').click()
                    destination = output / f'result-{cycle}.xlsx'; download.value.save_as(destination)
                    workbook = load_workbook(destination, read_only=True)
                    assert any('OK' in row for sheet in workbook for row in sheet.values)
                    workbook.close()
                assert not errors, errors
            finally:
                (output / 'page.txt').write_text(page.locator('body').inner_text(), encoding='utf-8')
                page.screenshot(path=str(output / 'result.png'), full_page=True)
                browser.close()
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=5)
        client.drop_database(config['database']); client.close()
