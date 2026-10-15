// UI guidance only. The runner remains authoritative for contracts and runtime values.
export function responsePaths(schema, prefix = '', depth = 0) {
  if (!schema || typeof schema !== 'object' || depth > 12) return [];
  const paths = [];
  for (const [name, child] of Object.entries(schema.properties || {})) {
    if (!/^\w+$/.test(name)) continue;
    const path = prefix ? `${prefix}.${name}` : name;
    paths.push(path, ...responsePaths(child, path, depth + 1));
  }
  if (schema.items) {
    const path = prefix ? `${prefix}.0` : '0';
    paths.push(path, ...responsePaths(schema.items, path, depth + 1));
  }
  for (const key of ['allOf', 'anyOf', 'oneOf']) {
    for (const part of schema[key] || []) paths.push(...responsePaths(part, prefix, depth + 1));
  }
  return [...new Set(paths)];
}

export function referenceChoices(steps, operations) {
  return steps.filter(step => /^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(step.name)).flatMap(step => {
    const op = operations.find(op => op.operationId === step.operationId);
    return responsePaths(op?.responseSchema).map(path => [`${step.name}.${path}`, `${step.name} → ${path}`]);
  });
}

export function validateFlowSettings(scenario, operations) {
  const available = new Set();
  const checkReferences = (value, label) => {
    if (typeof value === 'string' && value.includes('{{steps.')) {
      const match = /^\{\{steps\.([A-Za-z][A-Za-z0-9_]*)(?:\.([\w.]+))?\}\}$/.exec(value);
      if (!match || !available.has(match[1])) throw new Error(`${label}：参照先は、この手順より前にあるAPIを選んでください`);
    } else if (value && typeof value === 'object') {
      Object.values(value).forEach(item => checkReferences(item, label));
    }
  };
  const check = (step, label, main = false) => {
    const op = operations.find(op => op.operationId === step.request?.operationId);
    if (!op) throw new Error(`${label}：呼び出すAPIを選んでください`);
    const status = main ? step.response_check?.expect?.status : step.expect_status;
    if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error(`${label}：期待HTTPステータスは100〜599で入力してください`);
    checkReferences(step, label);
    if (!step.poll) return;
    const p = step.poll;
    if (op.method?.toUpperCase() !== 'GET') throw new Error(`${label}：完了待ちを使えるのはGETです。作成・更新APIは繰り返せません`);
    if (!p.path?.trim()) throw new Error(`${label}：完了を確認するレスポンス項目を選んでください`);
    if (!Number.isFinite(p.timeout) || p.timeout < 0.1 || p.timeout > 300) throw new Error(`${label}：期限は0.1〜300秒で入力してください`);
    if (!Number.isFinite(p.interval) || p.interval < 0.05 || p.interval > 60 || p.interval > p.timeout) throw new Error(`${label}：確認間隔は0.05〜60秒、かつ期限以下で入力してください`);
  };
  const flow = scenario.api_flow || {};
  for (const phase of ['before', 'cleanup']) {
    if ((flow[phase] || []).length > 20) throw new Error('前処理・後片付けはそれぞれ20手順以内にしてください');
  }
  for (const step of flow.before || []) { check(step, `前処理「${step.name}」`); available.add(step.name); }
  const main = {...scenario}; delete main.api_flow;
  check(main, '本試験', true); available.add('result');
  for (const step of flow.cleanup || []) { check(step, `後片付け「${step.name}」`); available.add(step.name); }
  return scenario;
}
