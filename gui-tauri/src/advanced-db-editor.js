// Declarative forms shared by browser and desktop; business rules are always explicit.
const el = (tag, text = '') => { const node = document.createElement(tag); node.textContent = text; return node; };
function field(parent, key, label, value = '', options = null) {
  const wrap = el('label', label), input = el(options ? 'select' : key === 'body' ? 'textarea' : 'input');
  input.dataset.advanced = key; input.setAttribute('aria-label', label);
  if (options) for (const [value, text] of options) { const option = el('option', text); option.value = value; input.append(option); }
  if (input.tagName === 'INPUT') input.type = 'text';
  input.value = value; if (key === 'body') input.rows = 4;
  wrap.className = 'form-field'; wrap.append(input); parent.append(wrap); return input;
}
const val = (node, key) => node.querySelector(`[data-advanced="${key}"]`).value.trim();
const names = (text) => text.split(',').map((s) => s.trim()).filter(Boolean);
const parse = (text, label) => { try { return JSON.parse(text); } catch { throw new Error(`${label}はJSONの値で入力してください（文字列は"文字列"）`); } };
function button(parent, text, action) { const b = el('button', text); b.type = 'button'; b.className = 'secondary'; b.onclick = action; parent.append(b); return b; }
function operand(parent, key, label) {
  field(parent, key + '-kind', label + 'の入力元', 'ref', [['ref', '項目を参照'], ['literal', '固定値']]);
  field(parent, key, label, '');
  return () => val(parent, key + '-kind') === 'ref' ? {ref: val(parent, key)} : {literal: parse(val(parent, key), label)};
}
function queryEditor(parent) {
  const panel = el('fieldset'); parent.append(panel); panel.append(el('legend', 'DB参照'));
  field(panel, 'engine', '参照するDB', 'postgres', [['postgres', 'PostgreSQL'], ['influxdb', 'InfluxDB 1.x']]);
  field(panel, 'table', '参照テーブル / measurement').dataset.dbTable = 'true';
  field(panel, 'columns', '取得カラム（カンマ区切り）');
  field(panel, 'order', '並び順のカラム（任意・昇順）');
  const rows = el('div'); panel.append(rows);
  button(panel, '検索条件を追加', () => {
    const row = el('fieldset'); rows.append(row);
    field(row, 'column', '条件カラム').dataset.dbColumn = 'true';
    field(row, 'operator', '比較', '=', ['=', '!=', '>', '>=', '<', '<=', 'in'].map((v) => [v, v]));
    row.collectOperand = operand(row, 'value', '検索値');
    button(row, '条件を削除', () => row.remove());
  });
  return () => ({engine: val(panel, 'engine'), table: val(panel, 'table'), columns: names(val(panel, 'columns')),
    order_by: names(val(panel, 'order')), filters: [...rows.children].map((row) => ({column: val(row, 'column'), operator: val(row, 'operator'), value: row.collectOperand()}))});
}
function calculation(parent, allowPoint = false) {
  const kind = field(parent, 'operation', '計算方法', 'direct', [['direct', 'そのまま'], ['string', '文字列に変換（例：IDをタグ値へ）'], ['mul', '掛け算'], ['add', '足し算'], ['sub', '引き算'], ['div', '割り算'], ['round', '四捨五入（第2入力は桁数）'], ['coalesce', '優先順：第1入力が未指定/nullなら第2入力'], ['sum', '配列の合計'], ['count', '配列の件数'], ['min', '配列の最小'], ['max', '配列の最大'], ['eq', '一致するか（真偽値）'], ['if', '条件分岐（条件、真の場合、偽の場合）']]);
  parent.append(el('p', `参照例：body.value、steps.site.0.site_id、steps.rows[].value${allowPoint ? '、point.value（変更前の値）' : ''}。falseや0も値として扱います。`));
  const inputs = [1, 2, 3].map((n) => { const box = el('div'); parent.append(box); return {box, collect: operand(box, 'arg' + n, '第' + n + '入力')}; });
  function arity() { return kind.value === 'if' ? 3 : ['direct', 'string', 'sum', 'count', 'min', 'max'].includes(kind.value) ? 1 : 2; }
  function update() { inputs.forEach((input, i) => { input.box.hidden = i >= arity(); }); }
  kind.onchange = update; update();
  return () => { const args = inputs.slice(0, arity()).map((input) => input.collect()); return kind.value === 'direct' ? args[0] : {op: kind.value, args}; };
}
export function buildAdvancedScenario(form) {
  if (!form.operation || !form.name.trim()) throw new Error('API操作と試験名を指定してください');
  const status = Number(form.status);
  if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error('期待statusを指定してください');
  const scenario = {name: form.name, request: {operationId: form.operation.operationId, body: form.requestBody,
    query_params: form.queryParams || {}, path_params: form.pathParams || {}}, response_check: {expect: {status, ...(form.emptyBody ? {empty_body: true} : {})}}};
  if (form.mode === 'expectation_rules') {
    if (!form.rules.assertions.length) throw new Error('照合先を1件以上設定してください');
    scenario.expectation_rules = form.rules;
  } else {
    if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(form.operation.method.toUpperCase())) throw new Error('一括変更の確認はPOST / PUT / PATCH / DELETEで設定してください');
    scenario.influx_mutation = form.bulk;
  }
  return scenario;
}
export function initAdvancedEditor(panel) {
  panel.replaceChildren();
  panel.append(el('p', 'API実行前に期待値を作り、実行後のレスポンスやDBと比較します。正解のルールは人が設定してください。DB参照は読み取り専用・最大5000行です。'));
  field(panel, 'body', '送信するJSON body', '{}'); field(panel, 'status', '期待HTTP status', '200');
  field(panel, 'empty', 'レスポンスボディ', 'false', [['false', 'OpenAPIの定義に従う'], ['true', '空であることを確認する']]);
  const steps = el('div'); panel.append(el('h4', '1. 期待値を作る処理（上から順に実行）'), steps);
  button(panel, '処理を追加', () => {
    const row = el('fieldset'); steps.append(row); row.append(el('legend', '期待値の処理'));
    field(row, 'name', '処理名（英数字）', 'step' + steps.children.length);
    const kind = field(row, 'kind', '処理の種類', 'query', [['query', 'DBを参照'], ['value', '計算・優先順位'], ['aggregate', 'グループ別に集計']]);
    const content = el('div'); row.append(content);
    function render() {
      content.replaceChildren();
      if (kind.value === 'query') row.collectContent = queryEditor(content);
      else if (kind.value === 'value') row.collectContent = calculation(content);
      else {
        const source = operand(content, 'source', '集計する行の配列');
        field(content, 'groups', 'グループのカラム（カンマ区切り）'); field(content, 'column', '集計カラム');
        field(content, 'aggregate', '集計方法', 'sum', [['sum', '合計'], ['count', '件数'], ['min', '最小'], ['max', '最大']]);
        field(content, 'output', '集計結果の項目名', 'total');
        row.collectContent = () => ({source: source(), group_by: names(val(content, 'groups')), column: val(content, 'column'), operation: val(content, 'aggregate'), output: val(content, 'output')});
      }
    }
    kind.onchange = render; render(); button(row, '処理を削除', () => row.remove());
  });
  const assertions = el('div'); panel.append(el('h4', '2. 照合する値'), assertions);
  button(panel, '照合先を追加', () => {
    const row = el('fieldset'); assertions.append(row);
    const source = field(row, 'source', '照合先', 'response', [['response', 'レスポンス'], ['db', '実行後のDB']]);
    const content = el('div'); row.append(content);
    function render() {
      content.replaceChildren();
      if (source.value === 'db') {
        row.collectQuery = queryEditor(content);
        field(content, 'value-path', '取得値のパス（空欄なら全行、例：0.amount）');
      } else field(content, 'path', 'レスポンスの項目（全体は$、例：data[].value）', '$');
    }
    source.onchange = render; render();
    row.collectExpected = operand(row, 'expected', '期待値');
    field(row, 'ordered', '配列の並び順', 'false', [['false', '順序を無視（重複は比較）'], ['true', '順序も一致']]);
    button(row, '照合を削除', () => row.remove());
  });
  return {body: () => parse(val(panel, 'body'), '送信body'), collect: () => ({mode: 'expectation_rules', status: val(panel, 'status'), emptyBody: val(panel, 'empty') === 'true', requestBody: parse(val(panel, 'body'), '送信body'), rules: {
    steps: [...steps.children].map((row) => ({name: val(row, 'name'), [val(row, 'kind')]: row.collectContent()})),
    assertions: [...assertions.children].map((row) => ({...(val(row, 'source') === 'db' ? {query: row.collectQuery(), ...(val(row, 'value-path') ? {value_path: val(row, 'value-path')} : {})} : {path: val(row, 'path')}), expected: row.collectExpected(), ordered: val(row, 'ordered') === 'true'})),
  }})};
}
export function initBulkEditor(panel) {
  panel.replaceChildren();
  panel.append(el('p', '確認範囲の全タグ・全フィールドを実行前後で比較します。開始・終了は両方含みます。対象外の変更を検出するため、確認範囲を変更対象より広く指定してください。範囲外は照合しません。データ投入・復旧は行いません。'));
  field(panel, 'measurement', 'measurement');
  field(panel, 'action', '期待する処理', 'update', [['update', '一括更新'], ['delete', '一括削除']]);
  field(panel, 'body', '送信するJSON body', '{}'); field(panel, 'status', '期待HTTP status', '200');
  field(panel, 'empty', 'レスポンスボディ', 'false', [['false', 'OpenAPIの定義に従う'], ['true', '空であることを確認する']]);
  for (const [key, label] of [['scope', '確認範囲'], ['target', '変更対象']]) {
    const box = el('fieldset'); panel.append(box); box.append(el('legend', label));
    field(box, key + '-start', label + 'の開始（タイムゾーン付き）');
    field(box, key + '-end', label + 'の終了（タイムゾーン付き）');
    field(box, key + '-tags', label + 'のタグ条件（JSON）', '{}');
  }
  const rows = el('div'); panel.append(rows);
  const add = button(panel, '変更するフィールドを追加', () => {
    const row = el('fieldset'); rows.append(row); field(row, 'name', 'フィールド名');
    row.collectExpr = calculation(row, true); button(row, 'フィールドを削除', () => row.remove());
  });
  panel.querySelector('[data-advanced="action"]').onchange = () => { rows.hidden = add.hidden = val(panel, 'action') === 'delete'; };
  return {body: () => parse(val(panel, 'body'), '送信body'), collect: () => ({mode: 'influx_bulk', status: val(panel, 'status'), emptyBody: val(panel, 'empty') === 'true', requestBody: parse(val(panel, 'body'), '送信body'), bulk: {
    measurement: val(panel, 'measurement'), action: val(panel, 'action'),
    ...Object.fromEntries(['scope', 'target'].map((key) => [key, {start: val(panel, key + '-start'), end: val(panel, key + '-end'), tags: parse(val(panel, key + '-tags'), 'タグ条件')}])),
    fields: val(panel, 'action') === 'delete' ? {} : uniqueFields([...rows.children].map((row) => [val(row, 'name'), row.collectExpr()])),
  }})};
}

function uniqueFields(entries) {
  if (new Set(entries.map(([name]) => name)).size !== entries.length) throw new Error('フィールド名が重複しています');
  return Object.fromEntries(entries);
}
