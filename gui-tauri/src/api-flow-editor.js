// A flow is one reviewed test. Named responses are local to that test, including reruns.
const clone = value => JSON.parse(JSON.stringify(value));
const el = (tag, text = '') => { const node = document.createElement(tag); node.textContent = text; return node; };
function field(parent, title, value = '', type = 'text') {
  const label = el('label', title); const input = el('input'); input.type = type; input.value = value; input.setAttribute('aria-label', title);
  label.append(input); parent.append(label); return input;
}
function button(parent, title, action) {
  const node = el('button', title); node.type = 'button'; node.className = 'secondary'; node.onclick = action; parent.append(node); return node;
}
function choice(parent, title, entries, value) {
  const label = el('label', title); const select = el('select'); select.setAttribute('aria-label', title);
  for (const [key, text] of entries) { const option = el('option', text); option.value = key; select.append(option); }
  if (value !== undefined) select.value = value;
  label.append(select); parent.append(label); return select;
}
function literal(text) {
  try { return JSON.parse(text); } catch { return text; }
}
function objectRows(parent, title, initial = {}, fields = []) {
  const group = el('fieldset'); group.append(el('legend', title)); parent.append(group);
  const rows = [];
  function add(name = '', value = '', enabled = true) {
    const row = el('div'); row.className = 'api-flow-value-row';
    const use = field(row, '送信', '', 'checkbox'); use.checked = enabled;
    const key = field(row, '項目名', name);
    const source = choice(row, '値の指定', [['fixed', '入力した値'], ['step', '前のAPIのレスポンス']], typeof value === 'string' && value.startsWith('{{steps.') ? 'step' : 'fixed');
    const kind = choice(row, '型', [['string','文字列'],['number','数値'],['boolean','真偽値'],['json','配列・オブジェクト・null']], typeof value === 'string' ? 'string' : ['number','boolean'].includes(typeof value) ? typeof value : 'json');
    const input = field(row, '値／手順名.レスポンス項目（例 create.id）', source.value === 'step' ? value.slice(8, -2) : typeof value === 'string' ? value : JSON.stringify(value));
    button(row, '削除', () => { row.remove(); rows.splice(rows.indexOf(entry), 1); });
    const entry = {row, use, key, source, input, kind}; rows.push(entry); group.append(row);
  }
  const names = new Set([...fields.map(f => f.name), ...Object.keys(initial)]);
  for (const name of names) {
    const schema = fields.find(f => f.name === name)?.schema || {};
    add(name, Object.hasOwn(initial, name) ? initial[name] : schema.example ?? '', Object.hasOwn(initial, name));
  }
  button(group, '項目を追加', () => add());
  return () => {
    const result = {};
    for (const row of rows.filter(r => r.use.checked)) {
      const key = row.key.value.trim();
      if (!key || ['__proto__', 'prototype', 'constructor'].includes(key) || Object.hasOwn(result, key)) throw new Error('項目名は空欄・重複にできません');
      const value = row.input.value;
      if (row.source.value === 'step' && !/^[A-Za-z][A-Za-z0-9_]*(\.[\w]+)*$/.test(value)) throw new Error('参照は create.id のように指定してください');
      let parsed = value;
      if (row.source.value !== 'step' && row.kind.value !== 'string') {
        try { parsed = JSON.parse(value); } catch { throw new Error('指定した型に合う値を入力してください'); }
        if (row.kind.value !== 'json' && typeof parsed !== row.kind.value) throw new Error('指定した型と値が一致しません');
      }
      result[key] = row.source.value === 'step' ? `{{steps.${value}}}` : parsed;
    }
    return result;
  };
}
function waitEditor(parent, initial) {
  const group = el('fieldset'); group.append(el('legend', '非同期処理の完了待ち（GETのみ）')); parent.append(group);
  const enabled = field(group, '完了するまで繰り返し確認する', '', 'checkbox'); enabled.checked = !!initial;
  const path = field(group, 'レスポンス項目（例 status）', initial?.path || '');
  const equals = field(group, '完了時の値（例 done）', initial ? JSON.stringify(initial.equals) : '');
  const timeout = field(group, '期限（秒、最大300）', initial?.timeout ?? 30, 'number');
  const interval = field(group, '確認間隔（秒）', initial?.interval ?? 1, 'number');
  const controls = [path, equals, timeout, interval];
  const update = () => controls.forEach(input => { input.disabled = !enabled.checked; }); enabled.onchange = update; update();
  return () => enabled.checked ? {path: path.value.trim(), equals: literal(equals.value), timeout: Number(timeout.value), interval: Number(interval.value)} : undefined;
}
function requestEditor(parent, operations, initial = {}, fixed = false) {
  const select = choice(parent, '呼び出すAPI', operations.map(op => [op.operationId, `${op.method} ${op.path} (${op.operationId})`]), initial.operationId);
  select.disabled = fixed;
  const values = el('div'); parent.append(values); let body, query, path;
  function render(req = {}) {
    values.replaceChildren();
    const op = operations.find(op => op.operationId === select.value);
    body = objectRows(values, 'リクエストボディ', req.body, Object.entries(op?.requestSchema?.properties || {}).map(([name, schema]) => ({name, schema})));
    path = objectRows(values, 'パスの値', req.path_params, (op?.parameters || []).filter(p => p.in === 'path'));
    query = objectRows(values, 'クエリの値', req.query_params, (op?.parameters || []).filter(p => p.in === 'query'));
  }
  select.onchange = () => render(); render(initial);
  return () => {
    const bodyValue = body();
    return {operationId: select.value, ...(Object.keys(bodyValue).length ? {body: bodyValue} : {}), path_params: path(), query_params: query()};
  };
}
function stepEditor(parent, operations, initial = {}) {
  const row = el('fieldset'); parent.append(row);
  const name = field(row, '手順名（英数字、例 create）', initial.name || '');
  const request = requestEditor(row, operations, initial.request);
  const status = field(row, '期待HTTPステータス', initial.expect_status ?? 200, 'number');
  const body = objectRows(row, 'レスポンスの期待値（項目パスと値）', initial.expect_body);
  const poll = waitEditor(row, initial.poll);
  return {row, read: () => ({name: name.value.trim(), request: request(), expect_status: Number(status.value), expect_body: body(), ...(poll() ? {poll: poll()} : {})})};
}
export function attachFlow(scenario, before, cleanup, poll) {
  const result = clone(scenario);
  const names = new Set(['result']);
  for (const step of [...before, ...cleanup]) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(step.name) || names.has(step.name)) throw new Error('手順名は重複しない英数字で指定してください。resultは本試験の予約名です');
    names.add(step.name);
    if (!step.request.operationId || !Number.isInteger(step.expect_status) || step.expect_status < 100 || step.expect_status > 599) throw new Error('API操作と期待HTTPステータスを指定してください');
  }
  if (before.length || cleanup.length) result.api_flow = {before, cleanup}; else delete result.api_flow;
  if (poll) result.poll = poll; else delete result.poll;
  return result;
}
export function flowControls(scenario, operations, onSave, onError) {
  const panel = el('details'); panel.append(el('summary', 'APIの連続実行・値の受け渡し・完了待ち'));
  panel.append(el('p', '前処理 → 本試験とDB照合 → 後片付けの順です。前処理が失敗したら本試験を止めます。後片付けは失敗時も試みます。作成APIは繰り返しません。'));
  const lists = {};
  for (const [phase, title] of [['before', '前処理API（上から順に実行）'], ['cleanup', '後片付けAPI（上から順に実行）']]) {
    const holder = el('fieldset'); holder.append(el('legend', title)); panel.append(holder); lists[phase] = [];
    const add = initial => { const editor = stepEditor(holder, operations, initial); lists[phase].push(editor); button(editor.row, 'この手順を削除', () => { editor.row.remove(); lists[phase].splice(lists[phase].indexOf(editor), 1); }); };
    for (const step of scenario.api_flow?.[phase] || []) add(step);
    button(holder, 'API手順を追加', () => add());
  }
  panel.className = 'api-flow-editor';
  panel.append(el('p', '本試験には create.id、後片付けには result.id のように参照を指定できます。値の型は保持されます。配列要素は items.0.id のように指定します。'));
  const mainRequest = requestEditor(panel, operations, scenario.request, true);
  const status = field(panel, '本試験の期待HTTPステータス', scenario.response_check?.expect?.status ?? 200, 'number');
  const expected = objectRows(panel, '本試験のレスポンス期待値（項目パスと値）', scenario.response_check?.expect?.body);
  const poll = waitEditor(panel, scenario.poll);
  button(panel, '連続実行の設定を反映', () => {
    try { onSave(attachFlow({...scenario, request: mainRequest(), response_check: {expect: {...scenario.response_check?.expect, status: Number(status.value), body: expected()}}}, lists.before.map(e => e.read()), lists.cleanup.map(e => e.read()), poll())); }
    catch (error) { onError(error.message); }
  });
  return panel;
}
export function newApiScenario(operation, name) {
  if (!operation || !name.trim()) throw new Error('API操作と試験名を指定してください');
  return {id: `ui-${globalThis.crypto.randomUUID()}`, name: name.trim(), request: {operationId: operation.operationId, body: {}}, response_check: {expect: {status: 200}}};
}
