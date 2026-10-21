// DDL is sent to the parser as text, never to a database.
export function initDdlCatalog(invoke) {
  const panel = document.getElementById('db-ddl-catalog');
  if (!panel) return;
  const status = panel.querySelector('[data-ddl-status]'), content = panel.querySelector('[data-ddl-result]');
  const tables = document.createElement('datalist'); tables.id = 'db-catalog-tables'; panel.append(tables);
  const columns = document.createElement('datalist'); columns.id = 'db-catalog-columns'; panel.append(columns);
  let catalog = null;
  function applyChoices() {
    document.querySelectorAll('input[data-db-table], #dbscenario-editor-table').forEach((input) => input.setAttribute('list', tables.id));
    document.querySelectorAll('input[data-db-column], input[aria-label="DBカラム"]').forEach((input) => input.setAttribute('list', columns.id));
  }
  function render() {
    content.replaceChildren(); tables.replaceChildren(); columns.replaceChildren();
    if (!catalog) return;
    const note = document.createElement('p'); note.textContent = catalog.note; content.append(note);
    for (const warning of catalog.warnings) { const p = document.createElement('p'); p.className = 'warning'; p.textContent = warning; content.append(p); }
    const seen = new Set();
    for (const table of catalog.tables) {
      const details = document.createElement('details'), summary = document.createElement('summary');
      summary.textContent = `${table.schema}.${table.name}（${table.columns.length}列）${table.mappingSelectable ? '' : '：通常の対応付け候補には含めません'}`;
      details.append(summary); content.append(details);
      if (table.mappingSelectable) { const opt = document.createElement('option'); opt.value = table.name; tables.append(opt); }
      const grid = document.createElement('table'); grid.className = 'data-table'; details.append(grid);
      for (const col of table.columns) {
        const row = document.createElement('tr'); grid.append(row);
        for (const value of [col.name, col.type, col.nullable ? 'NULL可' : 'NOT NULL', table.primaryKey.includes(col.name) ? '主キー' : '', col.generated || col.default || '']) {
          const cell = document.createElement('td'); cell.textContent = value; row.append(cell);
        }
        if (table.mappingSelectable && /^[A-Za-z_][A-Za-z0-9_]*$/.test(col.name) && !seen.has(col.name)) { const opt = document.createElement('option'); opt.value = col.name; columns.append(opt); seen.add(col.name); }
      }
      const constraints = document.createElement('pre'); constraints.textContent = JSON.stringify({primaryKey: table.primaryKey, unique: table.unique, foreignKeys: table.foreignKeys, checks: table.checks}, null, 2); details.append(constraints);
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
  new window.MutationObserver(applyChoices).observe(document.getElementById('page-db-scenario'), {childList: true, subtree: true});
}
