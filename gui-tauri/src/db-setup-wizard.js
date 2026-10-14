// Guide the existing editor without duplicating input values or changing saved scenarios.
const titles = ['APIを選ぶ', '送信値を入力', 'DBとの関係を設定', '試験内容を確認'];
const help = [
  '対象APIと確認する内容を選んでください。APIがない場合は「1. 対象を登録」で作成・読み込みできます。',
  '実際に送る値を入力します。DB列の対応付けは次の手順です。正常ケースでは実際に使える値を指定してください。',
  '保存先・検索条件・照合するDB列と期待ステータスを設定します。列名や業務上の正解は自動推測しません。',
  '送信内容と照合範囲を確認してください。「この対応設定を追加」後に保存できます。ここではまだ実行しません。',
];
const el = (tag, text = '') => { const node = document.createElement(tag); node.textContent = text; return node; };
const byId = id => document.getElementById(id);

export function initDbSetupWizard({getOperation, validateRequest, buildCases}) {
  const root = byId('dbscenario-setup');
  let stage = 1, reached = 1, all = false;
  const add = byId('dbscenario-editor-add-scenario');
  root.querySelector('.db-setup-actions').append(add);
  const nav = byId('dbsetup-nav'); nav.replaceChildren();
  const tabs = titles.map((title, index) => {
    const button = el('button', `${index+1}. ${title}`); button.type = 'button'; button.className = 'secondary';
    button.dataset.dbStage = String(index+1);
    button.onclick = () => go(index+1); nav.append(button); return button;
  });
  const mark = (node, phases) => { if (node) node.dataset.dbStep = phases; };
  const field = (id, phase) => mark(byId(id)?.closest('.form-field'), phase);
  function tagFields() {
    for (const id of ['dbscenario-editor-operation', 'dbscenario-editor-name', 'dbscenario-editor-mode']) field(id, '1');
    mark(byId('dbscenario-editor-operation').closest('.db-scenario-editor-grid'), '1 3');
    field('dbscenario-editor-engine', '1'); field('dbscenario-editor-table', '3');
    for (const name of ['sql', 'insert']) {
      const panel = byId(`dbscenario-${name}-panel`);
      for (const child of panel.children) mark(child, child.querySelector(`[data-${name}-field="body"]`) ? '2' : '3');
    }
    for (const panelId of ['dbscenario-editor-write-panel', 'dbscenario-editor-get-panel', 'dbscenario-editor-unchanged-panel', 'dbscenario-editor-influx-mutation']) {
      for (const child of byId(panelId).children) mark(child, '3');
    }
    mark(byId('dbscenario-editor-request-body-field'), '2');
    field('dbscenario-editor-unchanged-body', '2');
    mark(byId('dbscenario-editor-influx-delete-body-field'), '2');
    mark(byId('dbscenario-editor-get-panel').firstElementChild, '2');
    for (const id of ['dbscenario-editor-write-mappings', 'dbscenario-editor-read-filters']) mark(byId(id).closest('.form-field'), '2 3');
    const operation = getOperation();
    const mode = byId('dbscenario-editor-mode').value;
    for (const option of byId('dbscenario-editor-mode').options) {
      const unavailable = (option.value === 'sql_response' && operation?.method !== 'GET') || (option.value === 'insert_rows' && operation?.method !== 'POST');
      option.disabled = unavailable; option.hidden = unavailable;
    }
    byId('dbscenario-editor-engine').querySelector('option[value="influxdb"]').disabled = ['sql_response', 'insert_rows'].includes(mode);
  }
  function draw() {
    tagFields();
    for (const [id, title] of [['dbscenario-editor-write-mappings', 'APIへ送る値'], ['dbscenario-editor-read-filters', '検索条件として送る値']]) {
      const field = byId(id).closest('.form-field');
      const label = field.querySelector('.db-scenario-editor-heading label');
      label.dataset.originalText ||= label.textContent;
      label.textContent = !all && stage === 2 ? title : label.dataset.originalText;
      const caption = field.querySelector(':scope > .field-caption');
      if (caption) {
        caption.dataset.originalText ||= caption.textContent;
        caption.textContent = !all && stage === 2 ? '送信する値を入力してください。DB列との対応は次の手順で設定します。' : caption.dataset.originalText;
      }
    }
    root.dataset.stage = all ? 'all' : String(stage);
    byId('dbsetup-heading').textContent = all ? 'すべての設定を一覧で編集' : `${stage}. ${titles[stage-1]}`;
    byId('dbsetup-help').textContent = all ? '入力値は手順表示と共通です。試験内容を確認してから追加できます。' : help[stage-1];
    const operation = getOperation(), selected = byId('dbsetup-selected');
    selected.hidden = !operation || stage === 1 && !all;
    selected.textContent = operation ? `${operation.method} ${operation.path} ／ ${byId('dbscenario-editor-name').value}` : '';
    tabs.forEach((tab, index) => {
      tab.disabled = all || index+1 > reached;
      if (!all && stage === index+1) tab.setAttribute('aria-current', 'step'); else tab.removeAttribute('aria-current');
    });
    byId('dbsetup-back').hidden = all || stage === 1;
    byId('dbsetup-next').hidden = !all && stage === 4;
    byId('dbsetup-next').textContent = all ? '試験内容を確認' : `次へ：${titles[stage] || titles[3]}`;
    add.hidden = !all && stage !== 4;
    const toggle = byId('dbsetup-display');
    toggle.textContent = all ? '順番に設定する表示へ' : '全項目を一覧で編集'; toggle.setAttribute('aria-pressed', String(all));
  }
  function clearError() { byId('dbsetup-error').hidden = true; byId('dbsetup-error').textContent = ''; }
  function showError(error) {
    const message = error.message || String(error);
    byId('dbsetup-error').textContent = message; byId('dbsetup-error').hidden = false;
  }
  function checkOperation() {
    if (!getOperation()) throw new Error('対象のAPIを選択してください');
    if (!byId('dbscenario-editor-name').value.trim()) throw new Error('結果一覧に表示する試験名を入力してください');
  }
  function preview(cases) {
    const container = byId('dbsetup-preview'); container.replaceChildren();
    container.append(el('h4', `追加する試験：${cases.length}件`));
    container.append(el('p', '設定した範囲のみ照合します。列を対応付けていない項目はDBの値を確認しません。実行前のレビュー画面で未照合項目も確認できます。'));
    for (const scenario of cases) {
      const card = el('article'); card.className = 'db-setup-preview-card';
      card.append(el('strong', scenario.name));
      const expectation = scenario.response_check?.expect || {};
      const table = scenario.db_insert_check?.table || scenario.db_response_check?.table || scenario.db_check?.table;
      const checks = [];
      if (table) checks.push(`照合先：${table}`);
      if (scenario.db_sql_response_check) checks.push('SQLの取得結果とレスポンスを照合');
      if (scenario.db_unchanged) checks.push('指定したDB範囲が実行前後で変わらないこと');
      if (scenario.influx_mutation) checks.push(`InfluxDB：${scenario.influx_mutation.measurement}`);
      if (scenario.given?.length) checks.push(`実行前に${scenario.given.length}行を準備`);
      if (scenario.cleanup) checks.push('作成した行を試験後に削除');
      card.append(el('p', `期待ステータス：${expectation.status ?? '設定なし'}${expectation.empty_body ? ' ／ レスポンス本文なし' : ''}`));
      checks.forEach(text => card.append(el('p', text)));
      const request = el('details'); request.open = cases.length === 1;
      request.append(el('summary', 'APIへ送る内容'), el('pre', JSON.stringify(scenario.request, null, 2))); card.append(request);
      const definition = el('details'); definition.append(el('summary', 'DBの対応・期待値の詳細'), el('pre', JSON.stringify(scenario, null, 2))); card.append(definition);
      container.append(card);
    }
  }
  function go(target) {
    try {
      clearError();
      if (target > stage || all && target === 4) {
        checkOperation();
        if (target >= 3) validateRequest();
      }
      if (target === 4) preview(buildCases());
      stage = target; reached = Math.max(reached, stage); all = false; draw();
      byId('dbsetup-heading').focus({preventScroll: true});
      root.scrollIntoView?.({block:'start'});
    } catch (error) { showError(error); }
  }
  byId('dbsetup-next').onclick = () => go(all ? 4 : stage+1);
  byId('dbsetup-back').onclick = () => go(Math.max(1, stage-1));
  byId('dbsetup-display').onclick = () => { all = !all; clearError(); draw(); };
  const invalidate = event => {
    if (!event.target.matches('input,select,textarea')) return;
    reached = Math.min(reached, Math.max(1, stage));
    byId('dbsetup-preview').replaceChildren(); clearError();
    if (stage === 4) stage = 3;
    draw();
  };
  root.addEventListener('input', invalidate); root.addEventListener('change', invalidate);
  draw();
  return {
    refresh: draw,
    reset() { stage=1; reached=1; byId('dbsetup-preview').replaceChildren(); clearError(); draw(); },
    added() { byId('dbsetup-preview').replaceChildren(); stage=1; reached=1; draw(); },
  };
}
