import {beforeEach, expect, test, vi} from 'vitest';
import {initAdvancedEditor} from '../src/advanced-db-editor.js';
import {initDdlCatalog} from '../src/ddl-catalog.js';

let panel, editor;
const field = (node, key) => node.querySelector(`[data-advanced="${key}"]`);
const click = (node, text) => [...node.querySelectorAll('button')].find(button => button.textContent === text).click();
const set = (node, key, value) => { const input = field(node, key); input.value = value; input.dispatchEvent(new window.Event('change', {bubbles:true})); return input; };
beforeEach(() => {
  document.body.innerHTML = '<div id="panel"></div>';
  panel = document.getElementById('panel'); editor = initAdvancedEditor(panel, {requestSchema:{type:'object', properties:{value:{type:'number'}}}});
});

test('参照候補はリクエストと先行処理だけを示し、未定義の処理を入力欄で知らせる', () => {
  click(panel, '処理を追加'); click(panel, '処理を追加');
  const [first, second] = panel.querySelectorAll('[data-expected-step]');
  set(first, 'kind', 'value'); set(first, 'arg1', 'body.value');
  set(second, 'kind', 'value'); set(second, 'arg1', 'steps.step1');
  field(first, 'arg1').focus();
  let values = [...panel.querySelectorAll('datalist option')].map(option => option.value);
  expect(values).toContain('body.value'); expect(values).not.toContain('steps.step2');
  field(second, 'arg1').focus();
  values = [...panel.querySelectorAll('datalist option')].map(option => option.value);
  expect(values).toContain('steps.step1'); expect(values).not.toContain('steps.step2');
  set(second, 'arg1', 'steps.misspelled');
  expect(() => editor.collect()).toThrow('先に定義した処理名');
  expect(document.activeElement).toBe(field(second, 'arg1'));
  expect(field(second, 'arg1').getAttribute('aria-invalid')).toBe('true');
});

test('処理の切替で入力を失わず、文字列固定値にJSONの引用符を要求しない', () => {
  click(panel, '処理を追加'); const row = panel.querySelector('[data-expected-step]');
  set(row, 'table', 'readings'); set(row, 'columns', 'id,value');
  set(row, 'kind', 'value'); set(row, 'arg1-kind', 'text'); set(row, 'arg1', '日本語の値');
  expect(editor.collect().rules.steps[0].value).toEqual({literal:'日本語の値'});
  set(row, 'kind', 'query'); expect(field(row, 'table').value).toBe('readings');
  set(row, 'kind', 'value'); expect(field(row, 'arg1').value).toBe('日本語の値');
});

test('途中の処理を削除して追加しても処理名が重複しない', () => {
  click(panel, '処理を追加'); click(panel, '処理を追加');
  click(panel.querySelector('[data-expected-step]'), '処理を削除');
  click(panel, '処理を追加');
  const names = [...panel.querySelectorAll('[data-expected-step] [data-advanced="name"]')].map(input=>input.value);
  expect(new Set(names).size).toBe(2);
  set(panel.querySelector('[data-expected-step]:last-child'), 'name', names[0]);
  expect(()=>editor.collect()).toThrow('重複しない');
});

test('DDLのカラム候補を選んだテーブルに絞り、InfluxDBへは提示しない', async () => {
  document.body.innerHTML = `<div id="page-db-scenario"><details id="db-ddl-catalog"><input data-ddl-file type="file"><textarea></textarea><button data-ddl-import></button><button data-ddl-clear></button><p data-ddl-status></p><div data-ddl-result></div></details><div id="panel"></div></div>`;
  panel = document.getElementById('panel'); editor = initAdvancedEditor(panel);
  click(panel, '処理を追加');
  const table = name => ({name,schema:'public',mappingSelectable:true,columns:[{name:name+'_id',type:'INT',nullable:false}],primaryKey:[name+'_id'],unique:[],foreignKeys:[],checks:[]});
  initDdlCatalog(vi.fn(async()=>({version:1,note:'解析のみ',tables:[table('users'),table('sites')],warnings:[]})));
  await document.querySelector('[data-ddl-import]').onclick();
  const row = panel.querySelector('[data-expected-step]');
  click(row, '検索条件を追加'); set(row,'table','users');
  const column = field(row,'column');
  const choices = ()=>[...document.getElementById(column.getAttribute('list')).children].map(option=>option.value);
  expect(choices()).toEqual(['users_id']);
  set(row,'table','sites'); expect(choices()).toEqual(['sites_id']);
  set(row,'engine','influxdb'); expect(column.hasAttribute('list')).toBe(false);
  expect(field(row,'table').hasAttribute('list')).toBe(false);
});
