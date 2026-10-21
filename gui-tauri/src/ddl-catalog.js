// DDL is sent to the parser as text, never to a database.
export function initDdlCatalog(invoke) {
  const panel = document.getElementById('db-ddl-catalog');
  if (!panel) return;
  const status = panel.querySelector('[data-ddl-status]'), content = panel.querySelector('[data-ddl-result]');
  const tables = document.createElement('datalist'); tables.id = 'db-catalog-tables'; panel.append(tables);
  const columns = document.createElement('datalist'); columns.id = 'db-catalog-columns'; panel.append(columns);
  let catalog = null;
  let nextList = 0;
  function fillChoices(list, values) {
    const signature = JSON.stringify(values);
    if (list.dataset.signature === signature) return;
    list.dataset.signature = signature; list.replaceChildren();
    for (const value of values) { const option = document.createElement('option'); option.value = value; list.append(option); }
  }
  function applyChoices() {
    document.querySelectorAll('input[data-db-table], #dbscenario-editor-table').forEach((input) => {
      const query = input.closest('[data-db-query]');
      const engine = query?.querySelector('[data-advanced="engine"]')?.value || document.getElementById('dbscenario-editor-engine')?.value;
      if (engine === 'postgres') input.setAttribute('list', tables.id); else input.removeAttribute('list');
    });
    document.querySelectorAll('input[data-db-column], input[aria-label="DBカラム"]').forEach((input) => {
      const query = input.closest('[data-db-query]');
      const engine = query?.querySelector('[data-advanced="engine"]')?.value || document.getElementById('dbscenario-editor-engine')?.value;
      const tableName = query?.querySelector('[data-db-table]')?.value || document.getElementById('dbscenario-editor-table')?.value;
      const table = catalog?.tables.find(table => table.mappingSelectable && table.name === tableName);
      let choices = columns;
      if (query) {
        if (!query.dataset.columnList) {
          query.dataset.columnList = 'db-query-columns-' + (++nextList);
          const list = document.createElement('datalist'); list.id = query.dataset.columnList; query.append(list);
        }
        choices = document.getElementById(query.dataset.columnList);
      }
      fillChoices(choices, engine === 'postgres' && table ? table.columns.map(column => column.name).filter(name => /^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) : []);
      if (engine === 'postgres' && table) input.setAttribute('list', choices.id); else input.removeAttribute('list');
    });
  }
  function render() {
    content.replaceChildren(); tables.replaceChildren(); columns.replaceChildren(); delete columns.dataset.signature;
    if (!catalog) { applyChoices(); return; }
    const note = document.createElement('p'); note.textContent = catalog.note; content.append(note);
    for (const warning of catalog.warnings) { const p = document.createElement('p'); p.className = 'warning'; p.textContent = warning; content.append(p); }
    for (const table of catalog.tables) {
      const details = document.createElement('details'), summary = document.createElement('summary');
      summary.textContent = `${table.schema}.${table.name}（${table.columns.length}列）${table.mappingSelectable ? '' : '：通常の対応付け候補には含めません'}`;
      details.append(summary); content.append(details);
      if (table.mappingSelectable) { const opt = document.createElement('option'); opt.value = table.name; tables.append(opt); }
      const grid = document.createElement('table'); grid.className = 'data-table'; details.append(grid);
      const header = grid.createTHead().insertRow();
      for (const label of ['カラム', 'データ型', 'NULL', '主キー', '既定値・自動生成']) { const cell = document.createElement('th'); cell.textContent = label; header.append(cell); }
      for (const col of table.columns) {
        const row = document.createElement('tr'); grid.append(row);
        for (const value of [col.name, col.type, col.nullable ? 'NULL可' : 'NOT NULL', table.primaryKey.includes(col.name) ? '主キー' : '', col.generated || col.default || '']) {
          const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
        }
      }
      const constraints = document.createElement('pre'); constraints.textContent = [
        '主キー：' + (table.primaryKey.join(', ') || '定義なし'),
        ...table.foreignKeys.map(key => `外部キー：${key.columns.join(', ')} → ${key.table}（${key.targetColumns.join(', ') || '参照先の主キー'}）`),
        ...table.unique.map(keys => '一意制約：' + keys.join(', ')),
        ...table.checks.map(check => 'CHECK：' + check),
      ].join('\n'); details.append(constraints);
    }
    applyChoices();
  }
  panel.querySelector('[data-ddl-file]').onchange = async (event) => {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 2000000) { status.textContent = 'DDLは2MB以下で指定してください'; return; }
    panel.querySelector('textarea').value = await file.text();
  };
  panel.querySelector('[data-ddl-import]').onclick = async () => {
    status.textContent = '解析中…';
    try {
      catalog = await invoke('bridge_call', {command: 'parse_ddl_catalog', args: {text: panel.querySelector('textarea').value}});
      render(); status.textContent = `${catalog.tables.length}テーブルを読み込みました。DBへは実行していません。`;
      try { window.localStorage.setItem('otg-ddl-catalog', JSON.stringify(catalog)); } catch { status.textContent += ' このブラウザーへの保存はできませんでした。'; }
    } catch (error) { status.textContent = error.message || String(error); }
  };
  panel.querySelector('[data-ddl-clear]').onclick = () => { catalog = null; try { window.localStorage.removeItem('otg-ddl-catalog'); } catch { /* Storage may be disabled. */ } render(); status.textContent = '一覧を削除しました'; };
  try { catalog = JSON.parse(window.localStorage.getItem('otg-ddl-catalog')); if (catalog?.version === 1) render(); } catch { /* Ignore incompatible local cache. */ }
  document.getElementById('page-db-scenario').addEventListener('input', applyChoices);
  document.getElementById('page-db-scenario').addEventListener('change', applyChoices);
  new window.MutationObserver(applyChoices).observe(document.getElementById('page-db-scenario'), {childList: true, subtree: true});
}
