import {responsePaths} from './flow-guidance.js';

// Execution still consumes raw JSON; credentials never enter settings/local storage.
export function loginEditor({container, raw, token, header, format, templates, tokenChoices, status, enabled}) {
  let operation;
  const message = text => { status.textContent = text; };
  function render(op = operation) {
    operation = op;
    container.replaceChildren();
    let initial;
    try {
      initial = JSON.parse(raw.value || '{}');
      if (!initial || Array.isArray(initial) || typeof initial !== 'object') throw new Error();
    } catch { message('ログインボディのJSONを確認してください。入力内容は保持しています。'); return; }
    tokenChoices.replaceChildren(new window.Option('レスポンスから認証に使う項目を選択', ''));
    if (!op) { container.textContent = 'ログインAPIを選ぶと、登録した項目の入力欄が表示されます。'; return; }
    const properties = op.requestSchema?.properties || {};
    const required = new Set(op.requestSchema?.required || []);
    const rows = [];
    for (const name of new Set([...Object.keys(properties), ...Object.keys(initial)])) {
      const schema = properties[name] || {};
      const row = document.createElement('div'); row.className = 'login-value-row';
      const label = document.createElement('label'); label.textContent = `${name}${required.has(name) ? '（必須）' : '（任意）'}`;
      const input = document.createElement('input'); input.setAttribute('aria-label', `ログイン：${name}`);
      input.type = schema.format === 'password' || /password|secret|token/i.test(name) ? 'password' : 'text';
      input.autocomplete = 'off'; input.disabled = !enabled();
      const value = initial[name];
      input.value = value === undefined ? '' : typeof value === 'string' ? value : JSON.stringify(value);
      const useLabel = document.createElement('label');
      const use = document.createElement('input'); use.type = 'checkbox'; use.checked = Object.hasOwn(initial, name) || required.has(name); use.disabled = !enabled();
      use.setAttribute('aria-label', `ログイン：${name}を送信`); useLabel.append(use, '送信');
      const error = document.createElement('small'); error.className = 'error'; error.setAttribute('aria-live', 'polite');
      label.append(input); row.append(label, useLabel, error); container.append(row);
      rows.push({name, schema, input, use, error, initialText: input.value});
    }
    const update = () => {
      const body = {}; let valid = true;
      for (const row of rows) {
        row.error.textContent = ''; row.input.removeAttribute('aria-invalid');
        if (!row.use.checked) continue;
        let value = row.input.value;
        const original = initial[row.name];
        const type = row.schema.type || (Array.isArray(original) ? 'array' : original === null ? 'json' : typeof original === 'undefined' ? 'string' : typeof original);
        if (Object.hasOwn(initial, row.name) && value === row.initialText) {
          value = original;
        } else if (type && type !== 'string') {
          try {
            value = JSON.parse(value);
            if ((type === 'integer' && !Number.isInteger(value)) || (type === 'number' && typeof value !== 'number') || (type === 'boolean' && typeof value !== 'boolean') || (type === 'array' && !Array.isArray(value)) || (type === 'object' && (!value || Array.isArray(value) || typeof value !== 'object'))) throw new Error();
          } catch { row.error.textContent = `${type}の値を入力してください`; row.input.setAttribute('aria-invalid', 'true'); valid = false; }
        }
        Object.defineProperty(body, row.name, {value, enumerable:true, configurable:true});
      }
      // Block execution of stale credentials while any form value is invalid.
      if (valid) raw.value = JSON.stringify(body, null, 2);
      raw.setCustomValidity(valid ? '' : 'ログイン情報の入力エラーを修正してください');
      raw.dispatchEvent(new window.Event('input', {bubbles:true}));
      message(valid ? 'ログイン情報を更新しました。試験用アカウントを指定してください。' : 'ログイン情報に入力エラーがあります。各項目を確認してください。');
    };
    for (const row of rows) { row.input.oninput = update; row.use.onchange = update; }
    for (const path of responsePaths(op.responseSchema)) tokenChoices.add(new window.Option(path, path));
    tokenChoices.value = token.value;
  }
  raw.addEventListener('change', () => { raw.setCustomValidity(''); render(); });
  tokenChoices.addEventListener('change', () => {
    if (tokenChoices.value) { token.value = tokenChoices.value; token.dispatchEvent(new window.Event('change', {bubbles:true})); }
  });
  for (const [label, tokenPath, headerName, headerFormat] of [
    ['id → auth-key', 'id', 'auth-key', '{token}'],
    ['access_token → Bearer認証', 'access_token', 'Authorization', 'Bearer {token}'],
  ]) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'secondary'; button.textContent = label;
    button.onclick = () => {
      if (!enabled()) return;
      token.value = tokenPath; header.value = headerName; format.value = headerFormat; tokenChoices.value = tokenPath;
      for (const input of [token, header, format]) input.dispatchEvent(new window.Event('change', {bubbles:true}));
      message(`認証方式を設定しました：${label}。APIの仕様と一致することを確認してください。ログイン情報は変更していません。`);
    };
    templates.append(button);
  }
  return {render, syncEnabled() {
    for (const node of [...container.querySelectorAll('input'), ...templates.querySelectorAll('button'), tokenChoices]) node.disabled = !enabled();
  }};
}
