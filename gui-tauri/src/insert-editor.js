// Declarative mappings; never infer DB columns or execute user code.
const ident = /^[A-Za-z_][A-Za-z0-9_]*$/;
const pathPattern = /^[A-Za-z_][A-Za-z0-9_]*(?:\[\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\])?)*$/;

export function insertPaths(schema, prefix = "", depth = 0) {
  if (!schema || depth > 12) return [];
  if (schema.type === "array") {
    const path = `${prefix}[]`;
    return [{ path, array: true }, ...insertPaths(schema.items, path, depth + 1)];
  }
  const own = prefix ? [{ path: prefix, object: schema.type === "object" }] : [];
  return [...own, ...Object.entries(schema.properties || {}).filter(([, value]) => !value.readOnly)
    .flatMap(([key, value]) => insertPaths(value, prefix ? `${prefix}.${key}` : key, depth + 1))];
}

export function buildInsertScenario(form) {
  if (form.operation?.method.toUpperCase() !== "POST" || form.engine !== "postgres") throw new Error("複数行保存はPostgreSQLのPOST操作で設定してください");
  if (!ident.test(form.table)) throw new Error("保存先テーブル名を入力してください");
  const paths = new Set(insertPaths(form.operation.requestSchema).map((x) => x.path));
  if (!paths.has(form.rowsPath) || !form.rowsPath.endsWith("[]")) throw new Error("保存行に対応する配列を選択してください");
  const arrays = new Set(form.rowsPath.split(".").map((_, i, all) => all.slice(0, i + 1).join(".")).filter((p) => p.endsWith("[]")));
  const source = (path) => {
    if (!pathPattern.test(path) || !paths.has(path)) throw new Error(`リクエスト項目「${path}」がありません`);
    if (path.split(".").some((part, i, all) => part.endsWith("[]") && !arrays.has(all.slice(0, i + 1).join(".")))) throw new Error("別配列の項目は保存行に対応付けできません");
  };
  const columns = {};
  for (const item of form.insertMappings || []) {
    if (!item.column) continue;
    if (!ident.test(item.column) || Object.hasOwn(columns, item.column)) throw new Error("DB列名が不正、または重複しています");
    const rule = { ...item.rule };
    if (rule.kind === "request") { source(rule.path); }
    else if (rule.kind === "fixed") { if (!Object.hasOwn(rule, "value")) throw new Error("固定値を入力してください"); }
    else if (rule.kind === "datetime") {
      source(rule.date); source(rule.time);
      try { new Intl.DateTimeFormat("ja", { timeZone: rule.timezone }).format(); } catch { throw new Error("タイムゾーンを確認してください"); }
      if (!rule.timezone) throw new Error("タイムゾーンを指定してください");
    } else if (rule.kind === "runtime") {
      if (!Number.isFinite(rule.tolerance_seconds) || rule.tolerance_seconds < 0 || rule.tolerance_seconds > 3600) throw new Error("実行時刻の許容秒数を0〜3600で入力してください");
    } else if (rule.kind === "lookup") {
      source(rule.path); if (rule.preferred_path) source(rule.preferred_path);
      for (const key of ["table", "match_column", "value_column"]) if (!ident.test(rule.lookup[key])) throw new Error("参照元テーブルと列を入力してください");
    } else throw new Error("保存値の種類を選択してください");
    columns[item.column] = rule;
  }
  const keys = form.primaryKeys.split(",").map((s) => s.trim());
  if (!keys.length || new Set(keys).size !== keys.length || keys.some((k) => !ident.test(k) || !columns[k])) throw new Error("全主キー列をカンマ区切りで指定し、各列を対応付けてください");
  const status = Number(form.insertStatus);
  if (!Number.isInteger(status) || status < 200 || status > 299) throw new Error("保存成功のstatusを200〜299で入力してください");
  if (!form.requestBody || Array.isArray(form.requestBody) || typeof form.requestBody !== "object") throw new Error("送信ボディはJSONオブジェクトで入力してください");
  return { name: form.name, request: { operationId: form.operation.operationId, body: form.requestBody,
    path_params: form.pathParams || {}, query_params: form.queryParams || {} },
  response_check: { expect: { status, empty_body: !!form.emptyBody } },
  db_insert_check: { table: form.table, primary_key: keys, rows_path: form.rowsPath, columns } };
}

export function planInsertMappings() {
  const request = (path) => ({ kind: "request", path });
  const columns = {
    site_id: { kind: "lookup", path: "location_id", preferred_path: "site_id", lookup: {
      engine: "postgres", table: "t_site", match_column: "location_id", value_column: "site_id",
      cardinality: "one", value_type: "integer", on_empty: "unverified" } },
    use_id: request("type"), datetime: { kind: "datetime", date: "plans[].date", time: "plans[].controls[].time", timezone: "Asia/Tokyo" },
    created: { kind: "runtime", tolerance_seconds: 5 }, manual: { kind: "fixed", value: false },
    fixed: { kind: "fixed", value: false }, cpbs_type: { kind: "fixed", value: 0 }, force: request("force"), profit: request("plans[].profit"),
  };
  for (const name of ["buy", "sell", "charge", "discharge", "soc", "gen", "suppression", "correct_point"]) columns[name] = request(`plans[].controls[].${name}`);
  return Object.entries(columns).map(([column, rule]) => ({ column, rule }));
}

export function initInsertEditor(getOperation) {
  const panel = document.getElementById("dbscenario-insert-panel");
  const make = (tag, text = "") => { const el = document.createElement(tag); el.textContent = text; return el; };
  const control = (parent, name, text, choices, value = "") => {
    const label = make("label", text);
    const input = make(choices ? "select" : "input");
    input.dataset.insertField = name; input.setAttribute("aria-label", text);
    if (!choices) input.type = "text";
    if (choices) for (const [v, title] of choices) { const opt = make("option", title); opt.value = v; input.append(opt); }
    input.value = value; label.append(input); parent.append(label); return input;
  };
  const get = (name) => panel.querySelector(`[data-insert-field="${name}"]`);
  let rows;
  function addMapping(column = "", rule = { kind: "request", path: "" }) {
    const row = make("div"); row.className = "insert-mapping";
    control(row, "column", "保存先DB列", null, column);
    const kind = control(row, "kind", "保存値の種類", [["request", "リクエストの値 / JSON"], ["fixed", "固定値"],
      ["datetime", "日付と時刻を組み立てる"], ["runtime", "API実行時刻の範囲"], ["lookup", "優先項目 / DB参照"]], rule.kind);
    const fields = make("div"); fields.className = "insert-rule-fields"; row.append(fields);
    const choices = [["", "項目を選択"], ...insertPaths(getOperation()?.requestSchema).filter((p) => !p.array).map((p) => [p.path, p.path])];
    const render = () => {
      fields.replaceChildren();
      if (["request", "lookup"].includes(kind.value)) control(fields, "path", "リクエスト項目", choices, rule.path || "");
      if (kind.value === "request") control(fields, "missing", "項目省略時", [["error", "未設定として停止"], ["null", "DBのNULLを期待"]], rule.missing || "error");
      if (kind.value === "fixed") control(fields, "value", "固定値（JSON）", null, JSON.stringify(rule.value ?? null));
      if (kind.value === "datetime") {
        control(fields, "date", "日付の項目", choices, rule.date || ""); control(fields, "time", "時刻の項目", choices, rule.time || "");
        control(fields, "timezone", "タイムゾーン", null, rule.timezone || "");
      }
      if (kind.value === "runtime") control(fields, "tolerance_seconds", "実行前後の許容秒数", null, String(rule.tolerance_seconds ?? ""));
      if (kind.value === "lookup") {
        control(fields, "preferred_path", "指定されていれば優先する項目", choices, rule.preferred_path || "");
        control(fields, "engine", "参照元DB", [["postgres", "PostgreSQL"], ["influxdb", "InfluxDB 1.x"]], rule.lookup?.engine || "postgres");
        for (const [key, title] of [["table", "参照テーブル"], ["match_column", "リクエストと比較する列"], ["value_column", "取得する列"]]) control(fields, key, title, null, rule.lookup?.[key] || "");
        control(fields, "value_type", "取得値の型", [["as_is", "そのまま"], ["integer", "整数"], ["string", "文字列"]], rule.lookup?.value_type || "as_is");
      }
    };
    kind.addEventListener("change", render); render();
    const remove = make("button", "削除"); remove.type = "button"; remove.className = "secondary"; remove.addEventListener("click", () => row.remove()); row.append(remove);
    rows.append(row);
  }
  function render() {
    panel.replaceChildren();
    panel.append(make("p", "配列の各要素を保存行として照合します。保存先の全行を実行前後で比較するため、他の処理が更新しない検証DBを指定してください（最大5000行）。自動削除は行いません。"));
    control(panel, "rows_path", "1行に対応する配列", [["", "配列を選択"], ...insertPaths(getOperation()?.requestSchema).filter((p) => p.array).map((p) => [p.path, p.path])]);
    control(panel, "primary_key", "複合主キー（カンマ区切り）");
    control(panel, "status", "期待する成功status", null, getOperation()?.successStatus || "200");
    const empty = control(panel, "empty", "レスポンスボディが空であることを確認"); empty.type = "checkbox";
    const bodyLabel = make("label", "送信するリクエスト（JSON）"); const body = make("textarea"); body.rows = 10; body.dataset.insertField = "body"; body.setAttribute("aria-label", "複数行保存のリクエスト"); body.value = "{}"; bodyLabel.append(body); panel.append(bodyLabel);
    rows = make("div"); rows.id = "dbscenario-insert-mappings"; panel.append(rows);
    const add = make("button", "保存列の対応を追加"); add.type = "button"; add.className = "secondary"; add.addEventListener("click", () => addMapping()); panel.append(add);
    const sample = make("button", "計画保存の対応例を設定"); sample.type = "button"; sample.className = "secondary";
    sample.addEventListener("click", () => {
      get("rows_path").value = "plans[].controls[]"; get("primary_key").value = "datetime,created,site_id,use_id"; get("empty").checked = true;
      document.getElementById("dbscenario-editor-table").value = "h_plan";
      rows.replaceChildren(); planInsertMappings().forEach(({ column, rule }) => addMapping(column, rule));
    }); panel.append(sample);
    panel.append(make("p", "対応例は明示した計画保存仕様です。参照テーブル・時刻の許容秒数・DB列を確認し、送信値を入力してください。"));
  }
  function collect() {
    const mappings = [...rows.children].map((row) => {
      const v = (key) => row.querySelector(`[data-insert-field="${key}"]`)?.value.trim();
      const kind = v("kind"), rule = { kind };
      if (kind === "request") Object.assign(rule, { path: v("path"), missing: v("missing") });
      if (kind === "fixed") rule.value = JSON.parse(v("value"));
      if (kind === "datetime") for (const key of ["date", "time", "timezone"]) rule[key] = v(key);
      if (kind === "runtime") { if (!v("tolerance_seconds")) throw new Error("許容秒数を入力してください"); rule.tolerance_seconds = Number(v("tolerance_seconds")); }
      if (kind === "lookup") Object.assign(rule, { path: v("path"), preferred_path: v("preferred_path"), lookup: {
        engine: v("engine"), table: v("table"), match_column: v("match_column"), value_column: v("value_column"),
        value_type: v("value_type"), cardinality: "one", on_empty: "unverified" } });
      return { column: v("column"), rule };
    });
    return { rowsPath: get("rows_path").value, primaryKeys: get("primary_key").value, insertStatus: get("status").value,
      requestBody: JSON.parse(get("body").value), emptyBody: get("empty").checked, insertMappings: mappings };
  }
  render();
  return { render, collect };
}
