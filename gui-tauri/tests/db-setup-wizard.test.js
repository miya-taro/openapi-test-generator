import { beforeEach, expect, test, vi } from 'vitest';
import { initDbScenarioEditor } from '../src/db-scenario-editor.js';

const initialBody = document.body.innerHTML;
const byId = id => document.getElementById(id);
const operation = { operationId: 'create', method: 'POST', path: '/values', parameters: [], successStatus: '201',
  requestSchema: { type: 'object', required: ['value'], properties: { value: { type: 'integer' } } } };
const click = id => byId(id).click();
const fill = (node, value) => { node.value = value; node.dispatchEvent(new window.Event('input', { bubbles: true })); };
const stage = () => byId('dbscenario-setup').dataset.stage;
const row = () => document.querySelector('#dbscenario-editor-write-mappings tr[data-field-path="value"]');
beforeEach(() => { document.body.innerHTML = initialBody; });
async function setup(op = operation) {
  const invoke = vi.fn(async (_command, payload) => payload?.command === 'list_db_scenario_operations' ? [op] : 'checks.yaml');
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
  await editor.load('openapi.json');
  return editor;
}
function select() {
  byId('dbscenario-editor-operation').value = 'create';
  byId('dbscenario-editor-operation').dispatchEvent(new window.Event('change', { bubbles: true }));
}

test('API・送信値・DB関係を段階ごとに検証し、戻っても値を保持する', async () => {
  await setup();
  expect(stage()).toBe('1');
  click('dbsetup-next');
  expect(byId('dbsetup-error').textContent).toContain('APIを選択');
  select(); click('dbsetup-next');
  expect(stage()).toBe('2');
  fill(row().querySelector('[data-api-value]'), ''); click('dbsetup-next');
  expect(stage()).toBe('2');
  expect(byId('dbsetup-error').hidden).toBe(false);
  fill(row().querySelector('[data-api-value]'), '17'); click('dbsetup-back');
  expect(stage()).toBe('1'); click('dbsetup-next'); click('dbsetup-next');
  expect(stage()).toBe('3');
  expect(row().querySelector('[data-api-value]').value).toBe('17');
  click('dbsetup-next');
  expect(stage()).toBe('3');
  expect(byId('dbsetup-error').hidden).toBe(false);
  fill(byId('dbscenario-editor-table'), 'values');
  fill(row().querySelector('[aria-label="DBカラム"]'), 'reading');
  row().querySelector('[aria-label="保存後の照合に使う"]').click();
  click('dbsetup-next');
  expect(stage()).toBe('4');
  expect(byId('dbsetup-preview').textContent).toContain('期待ステータス：201');
  expect(byId('dbsetup-preview').textContent).toContain('"reading": 17');
  expect(byId('dbscenario-editor-add-scenario').hidden).toBe(false);
  click('dbscenario-editor-add-scenario');
  const saved = JSON.parse(document.querySelector('#dbscenario-editor-scenario-list pre').textContent);
  expect(saved.request.body).toEqual({ value: 17 });
  expect(saved.db_check.expect.columns).toEqual({ reading: 17 });
  expect(stage()).toBe('1');
});

test('前の段階で修正すると古いプレビューへ直接進めず、一覧表示でも値を共有する', async () => {
  await setup(); select(); click('dbsetup-next'); click('dbsetup-next');
  fill(byId('dbscenario-editor-table'), 'values');
  fill(row().querySelector('[aria-label="DBカラム"]'), 'reading');
  row().querySelector('[aria-label="保存後の照合に使う"]').click();
  click('dbsetup-next');
  document.querySelector('[data-db-stage="2"]').click();
  fill(row().querySelector('[data-api-value]'), '42');
  expect(byId('dbsetup-preview').textContent).toBe('');
  expect(document.querySelector('[data-db-stage="4"]').disabled).toBe(true);
  click('dbsetup-display');
  expect(stage()).toBe('all');
  expect(row().querySelector('[data-api-value]').value).toBe('42');
  click('dbsetup-next');
  expect(stage()).toBe('4');
  expect(byId('dbsetup-preview').textContent).toContain('"reading": 42');
});

test('複数行保存は送信JSONの構文を先に検証し、対応しないメソッドの選択肢を隠す', async () => {
  await setup(); select();
  expect(byId('dbscenario-editor-mode').querySelector('[value="sql_response"]').hidden).toBe(true);
  byId('dbscenario-editor-mode').value = 'insert_rows';
  byId('dbscenario-editor-mode').dispatchEvent(new window.Event('change', { bubbles: true }));
  expect(byId('dbscenario-editor-engine').querySelector('[value="influxdb"]').disabled).toBe(true);
  click('dbsetup-next');
  const body = document.querySelector('[data-insert-field="body"]');
  fill(body, '{'); click('dbsetup-next');
  expect(stage()).toBe('2');
  fill(body, '{"value":17}'); click('dbsetup-next');
  expect(stage()).toBe('3');
  click('dbsetup-back'); expect(body.value).toBe('{"value":17}');
});

test('DB変更なしケースは意図した不正な送信値を許可する', async () => {
  await setup(); select();
  byId('dbscenario-editor-mode').value = 'unchanged';
  byId('dbscenario-editor-mode').dispatchEvent(new window.Event('change', { bubbles: true }));
  click('dbsetup-next'); fill(byId('dbscenario-editor-unchanged-body'), '{"value":"wrong"}');
  click('dbsetup-next'); expect(stage()).toBe('3');
  fill(byId('dbscenario-editor-table'), 'values');
  fill(byId('dbscenario-editor-unchanged-status'), '400');
  fill(byId('dbscenario-editor-unchanged-columns'), 'value');
  click('dbsetup-next'); expect(stage()).toBe('4');
  expect(byId('dbsetup-preview').textContent).toContain('期待ステータス：400');
});
