// Human-authored SELECT + explicit grouping. No inference of business rules.
export function responsePaths(schema, prefix = '', depth = 0) {
  if (!schema || depth > 12) return [];
  if (schema.type === 'array') return [{path: `${prefix}[]`, array: true}, ...responsePaths(schema.items, `${prefix}[]`, depth + 1)];
  return [...(prefix ? [{path: prefix}] : []), ...Object.entries(schema.properties || {}).flatMap(([name, child]) => responsePaths(child, prefix ? `${prefix}.${name}` : name, depth + 1))];
}

export function buildSqlResponseScenario(form) {
  if (form.operation?.method.toUpperCase() !== 'GET' || form.engine !== 'postgres') throw new Error('SQLレスポンス照合はPostgreSQLのGETで設定してください');
  const check = form.sqlCheck;
  if (!/^\s*(SELECT|WITH)\b/i.test(check.sql) || check.sql.trim().replace(/;$/, '').includes(';')) throw new Error('期待値SQLはSELECTまたはWITHの1文で入力してください');
  if (!Object.keys(check.fields).length) throw new Error('レスポンスとSQL列を対応付けてください');
  const paths = new Set(responsePaths(form.operation.responseSchema).map((p) => p.path));
  const ident = /^[A-Za-z_][A-Za-z0-9_]*$/;
  for (const [path, column] of Object.entries(check.fields)) {
    if (!paths.has(path) || !ident.test(column)) throw new Error('レスポンス項目・SQL列名を確認してください');
    if (Object.keys(check.fields).some((p) => p.startsWith(path + '.'))) throw new Error('オブジェクト全体と中身は同時に対応付けできません');
  }
  for (const [name, rule] of Object.entries(check.parameters)) if (!ident.test(name) || !rule.path) throw new Error('SQLパラメータ名・リクエスト項目を入力してください');
  const status = Number(form.sqlStatus);
  if (!Number.isInteger(status) || status < 200 || status > 299) throw new Error('期待する成功statusを200〜299で入力してください');
  if (!form.requestBody || typeof form.requestBody !== 'object' || Array.isArray(form.requestBody)) throw new Error('送信JSONはオブジェクトで入力してください');
  return {name: form.name, request: {operationId: form.operation.operationId, body: form.requestBody, query_params: form.queryParams || {}, path_params: form.pathParams || {}}, response_check: {expect: {status}}, db_sql_response_check: check};
}

export function initSqlResponseEditor(getOperation) {
  const panel = document.getElementById('dbscenario-sql-panel');
  const make = (tag, text = '') => { const el = document.createElement(tag); el.textContent = text; return el; };
  function input(parent, name, label, value = '', choices = null, multiline = false) {
    const wrapper = make('label', label), el = make(choices ? 'select' : multiline ? 'textarea' : 'input');
    el.dataset.sqlField = name; el.setAttribute('aria-label', label);
    if (choices) for (const [val, text] of choices) { const option = make('option', text); option.value = val; el.append(option); }
    if (!choices && !multiline) el.type = 'text';
    if (multiline) el.rows = 8;
    el.value = value; wrapper.append(el); parent.append(wrapper); return el;
  }
  let mappings, groups, parameters;
  const value = (name, parent = panel) => parent.querySelector(`[data-sql-field="${name}"]`).value.trim();
  function addParameter(name = '', rule = {}) {
    const row = make('div'); row.className = 'insert-mapping';
    input(row, 'name', 'SQLパラメータ名', name);
    input(row, 'source', '入力場所', rule.source || 'body', [['body', 'JSON body'], ['query', 'クエリ'], ['path', 'パス']]);
    input(row, 'path', 'リクエスト項目', rule.path || name);
    input(row, 'missing', '省略時', rule.missing || 'error', [['error', '未設定として停止'], ['null', 'SQLのNULLを渡す']]);
    const remove = make('button', '削除'); remove.type = 'button'; remove.className = 'secondary'; remove.onclick = () => row.remove(); row.append(remove); parameters.append(row);
  }
  function render() {
    panel.replaceChildren();
    panel.append(make('p', '期待値取得SQLとレスポンスへの対応を設定します。SQLは読み取り専用、30秒・5000行までです。APIと同じSQLを使うだけでは検索ロジックの誤りを検出できないため、正解の分かるデータでも検証してください。'));
    input(panel, 'sql', '期待値取得SQL', '', null, true);
    panel.append(make('p', 'リクエスト値は %(site_id)s のように指定します。文字列の引用符は不要です。省略時NULLなら、SQL側で IS NULL などの条件を書いてください。'));
    parameters = make('div'); panel.append(parameters);
    const add = make('button', 'SQLパラメータを追加'); add.type = 'button'; add.className = 'secondary'; add.onclick = () => addParameter(); panel.append(add);
    input(panel, 'body', '送信するリクエスト（JSON body）', '{}', null, true);
    input(panel, 'status', '期待する成功status', getOperation()?.successStatus || '200');
    groups = make('div'); panel.append(make('h4', '配列のまとめ方'), groups);
    mappings = make('div'); panel.append(make('h4', 'レスポンス項目 → SQL結果の列名'), mappings);
    for (const entry of responsePaths(getOperation()?.responseSchema)) {
      const row = make('div'); row.dataset.responsePath = entry.path;
      if (entry.array) {
        input(row, 'group_by', `${entry.path} のグループ列（カンマ区切り・空欄なら1行1要素）`);
        input(row, 'order', `${entry.path} の並び順`, 'ignore', [['ignore', '順序を無視'], ['ordered', 'SQL結果の順序と一致']]); groups.append(row);
      } else { input(row, 'column', entry.path); mappings.append(row); }
    }
    const sample = make('button', '計画取得の対応例を設定'); sample.type = 'button'; sample.className = 'secondary';
    sample.onclick = () => {
      parameters.replaceChildren();
      for (const name of ['site_id', 'location_id', 'start', 'end', 'correct', 'type']) addParameter(name, {missing: ['start', 'end'].includes(name) ? 'error' : 'null'});
      for (const row of groups.children) row.querySelector('[data-sql-field="group_by"]').value = row.dataset.responsePath === 'plans[]' ? 'plan_date,use_id' : '';
      const fields = {site_id: 'site_id', start_datetime: 'start_datetime', end_datetime: 'end_datetime', 'plans[].date': 'plan_date', 'plans[].profit': 'profit', 'plans[].type': 'use_id', 'plans[].controls[].time': 'control_time'};
      for (const name of ['correct', 'buy', 'sell', 'charge', 'discharge', 'soc', 'gen', 'suppression', 'correct_point']) fields[`plans[].controls[].${name}`] = name;
      for (const row of mappings.children) row.querySelector('input').value = fields[row.dataset.responsePath] || '';
    }; panel.insertBefore(sample, panel.children[1]);
    panel.append(make('p', '例：plans[] は plan_date,use_id でまとめ、controls[] は空欄で1行1要素にします。correct_pointはJSON列全体か、中の項目のいずれかを対応付けます。空欄の項目はDB照合対象外です。'));
  }
  function collect() {
    const params = {};
    for (const row of parameters.children) {
      const name = value('name', row);
      if (!name || Object.hasOwn(params, name)) throw new Error('SQLパラメータ名が空欄、または重複しています');
      params[name] = {source: value('source', row), path: value('path', row), missing: value('missing', row)};
    }
    const fields = Object.fromEntries([...mappings.children].map((row) => [row.dataset.responsePath, value('column', row)]).filter(([, col]) => col));
    const arrays = [...groups.children].filter((row) => Object.keys(fields).some((path) => path.startsWith(row.dataset.responsePath + '.'))).map((row) => ({path: row.dataset.responsePath, group_by: value('group_by', row).split(',').map((s) => s.trim()).filter(Boolean), ordered: value('order', row) === 'ordered'}));
    return {sqlCheck: {sql: value('sql'), parameters: params, fields, arrays}, sqlStatus: value('status'), requestBody: JSON.parse(value('body'))};
  }
  render(); return {render, collect};
}
