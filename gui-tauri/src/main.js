import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open, save } from "@tauri-apps/plugin-dialog";

function $(id) {
  return document.getElementById(id);
}

// ---------- 設定の読み込み/保存（PySide6版と同じ設定ファイルを共有） ----------

let settings = {};

async function loadSettingsIntoForm() {
  settings = await invoke("load_settings");
  $("openapi-path").value = settings.shared_openapi_path || "";
  $("output-dir").value = settings.gen_output_dir || "";
  $("base-url").value = settings.gen_base_url || "";
  $("setup-sql-path").value = settings.gen_setup_path || "";
  $("teardown-sql-path").value = settings.gen_teardown_path || "";
  $("dry-run").checked = !!settings.gen_dry_run;
  $("full-body").checked = !!settings.gen_full_body;
  $("fail-fast").checked = !!settings.gen_fail_fast;
  $("hc-path").value = settings.hc_path || "";

  $("pg-enabled").checked = !!settings.cfg_pg_enabled;
  $("pg-host").value = settings.cfg_pg_host || "";
  $("pg-port").value = settings.cfg_pg_port || "";
  $("pg-dbname").value = settings.cfg_pg_dbname || "";
  $("pg-schema").value = settings.cfg_pg_schema || "";
  $("pg-user").value = settings.cfg_pg_user || "";
  // password は設定ファイルに平文保存しないため、起動時は毎回未入力にする
  $("influx-enabled").checked = !!settings.cfg_influx_enabled;
  $("influx-host").value = settings.cfg_influx_host || "";
  $("influx-port").value = settings.cfg_influx_port || "";
  $("influx-database").value = settings.cfg_influx_database || "";
  $("influx-username").value = settings.cfg_influx_username || "";

  $("auth-enabled").checked = !!settings.auth_enabled;
  $("auth-token-path").value = settings.auth_token_path || "";
  $("auth-header-name").value = settings.auth_header_name || "";
  $("auth-header-format").value = settings.auth_header_format || "";
  // ボディは認証情報を含みうるため、設定ファイルに平文保存しない（起動時は毎回未入力）

  $("dbprep-sql-tables").value = settings.dbprep_sql_tables || "";
  $("dbprep-sql-output-dir").value = settings.dbprep_sql_output_dir || "";
  $("dbprep-mapping-output").value = settings.dbprep_mapping_output || "";
  $("dbprep-scenario-mapping-path").value = settings.dbprep_scenario_mapping_path || "";
  $("dbprep-scenario-output").value = settings.dbprep_scenario_output || "";
  $("dbscenario-path").value = settings.dbscenario_path || "";
  $("dbscenario-report-output").value = settings.dbscenario_report_output || "";
  $("dbscenario-dry-run").checked = !!settings.dbscenario_dry_run;

  updateActiveOpenapiText();
  updateActiveBaseUrlText();
  updateActiveDbConfigText();

  await refreshOperationsList({ keepExcluded: true });
  // ログイン操作の選択はoperation一覧に依存するため、一覧更新後に復元する。
  // value を直接書き換えても change イベントは発火しないため、ボディ/token_pathの
  // 自動入力を明示的に呼び直す（呼ばないと「選択済みなのに毎回空欄」になる）。
  if (settings.auth_login_op) {
    $("auth-login-op").value = settings.auth_login_op;
    await applyLoginOperationHints();
  }
}

async function persistSettings() {
  settings.shared_openapi_path = $("openapi-path").value.trim();
  settings.gen_output_dir = $("output-dir").value.trim();
  settings.gen_base_url = $("base-url").value.trim();
  settings.gen_setup_path = $("setup-sql-path").value.trim();
  settings.gen_teardown_path = $("teardown-sql-path").value.trim();
  settings.gen_dry_run = $("dry-run").checked;
  settings.gen_full_body = $("full-body").checked;
  settings.gen_fail_fast = $("fail-fast").checked;
  settings.hc_path = $("hc-path").value.trim();
  settings.gen_excluded_operations = getUncheckedOperationIds().join(",");

  settings.cfg_pg_enabled = $("pg-enabled").checked;
  settings.cfg_pg_host = $("pg-host").value.trim();
  settings.cfg_pg_port = $("pg-port").value.trim();
  settings.cfg_pg_dbname = $("pg-dbname").value.trim();
  settings.cfg_pg_schema = $("pg-schema").value.trim();
  settings.cfg_pg_user = $("pg-user").value.trim();
  settings.cfg_influx_enabled = $("influx-enabled").checked;
  settings.cfg_influx_host = $("influx-host").value.trim();
  settings.cfg_influx_port = $("influx-port").value.trim();
  settings.cfg_influx_database = $("influx-database").value.trim();
  settings.cfg_influx_username = $("influx-username").value.trim();
  // password は意図的に保存しない（設定ファイルへの平文保存を避けるため）

  settings.auth_enabled = $("auth-enabled").checked;
  settings.auth_login_op = $("auth-login-op").value;
  settings.auth_token_path = $("auth-token-path").value.trim();
  settings.auth_header_name = $("auth-header-name").value.trim();
  settings.auth_header_format = $("auth-header-format").value.trim();
  // ボディ（認証情報を含みうる）は意図的に保存しない

  settings.dbprep_sql_tables = $("dbprep-sql-tables").value.trim();
  settings.dbprep_sql_output_dir = $("dbprep-sql-output-dir").value.trim();
  settings.dbprep_mapping_output = $("dbprep-mapping-output").value.trim();
  settings.dbprep_scenario_mapping_path = $("dbprep-scenario-mapping-path").value.trim();
  settings.dbprep_scenario_output = $("dbprep-scenario-output").value.trim();
  settings.dbscenario_path = $("dbscenario-path").value.trim();
  settings.dbscenario_report_output = $("dbscenario-report-output").value.trim();
  settings.dbscenario_dry_run = $("dbscenario-dry-run").checked;

  await invoke("save_settings", { data: settings });
}

// ---------- ファイル/フォルダ選択 ----------

async function browseFile(inputId, filters, onPicked) {
  const picked = await open({ multiple: false, filters });
  if (picked) {
    $(inputId).value = picked;
    if (onPicked) await onPicked(picked);
  }
}

async function browseDir(inputId) {
  const picked = await open({ directory: true });
  if (picked) $(inputId).value = picked;
}

async function browseSaveFile(inputId, filters, defaultPath) {
  const picked = await save({ filters, defaultPath });
  if (picked) $(inputId).value = picked;
}

// ---------- サイドバーナビゲーション ----------

function showPage(pageId) {
  document.querySelectorAll("#top-nav .tab[data-page]").forEach((el) => el.classList.toggle("active", el.dataset.page === pageId));
  document.querySelectorAll(".page").forEach((el) => el.classList.toggle("active", el.id === `page-${pageId}`));
}

for (const tab of document.querySelectorAll("#top-nav .tab[data-page]")) {
  tab.addEventListener("click", () => showPage(tab.dataset.page));
}

// ---------- openapi.json（「設定」画面） ----------

function updateActiveOpenapiText() {
  const path = $("openapi-path").value.trim();
  const name = path ? path.split(/[\\/]/).pop() : "未設定";
  document.querySelectorAll(".status-openapi-text").forEach((el) => (el.textContent = `openapi.json: ${name}`));
}

function updateActiveBaseUrlText() {
  const url = $("base-url").value.trim();
  document.querySelectorAll(".status-baseurl-text").forEach((el) => (el.textContent = `Base URL: ${url || "未設定"}`));
}

for (const evt of ["input", "change"]) {
  $("base-url").addEventListener(evt, updateActiveBaseUrlText);
}

for (const btn of document.querySelectorAll(".goto-settings-btn")) {
  btn.addEventListener("click", () => showPage("settings"));
}

// ---------- API疎通確認（「設定」画面、DB接続設定の「接続確認」と対になる任意の疎通確認） ----------

function setHcStatus(text, state) {
  const el = $("hc-status");
  el.textContent = text;
  el.classList.remove("error", "ok");
  if (state) el.classList.add(state);
}

$("hc-run-button").addEventListener("click", async () => {
  const baseUrl = $("base-url").value.trim();
  if (!baseUrl) {
    setHcStatus("Base URL を入力してください", "error");
    return;
  }
  const healthPath = $("hc-path").value.trim() || "/health";
  $("hc-run-button").disabled = true;
  setHcStatus("確認中...", null);
  try {
    const ok = await invoke("bridge_call", { command: "health_check", args: { base_url: baseUrl, health_path: healthPath } });
    setHcStatus(ok ? `OK: ${baseUrl}${healthPath} から2xxが返りました` : `NG: ${baseUrl}${healthPath} から2xxが返りませんでした`, ok ? "ok" : "error");
  } catch (e) {
    setHcStatus(`確認に失敗しました: ${e}`, "error");
  } finally {
    $("hc-run-button").disabled = false;
  }
});

$("browse-openapi").addEventListener("click", () =>
  browseFile("openapi-path", [{ name: "JSON", extensions: ["json"] }], () => {
    updateActiveOpenapiText();
    return refreshOperationsList({ keepExcluded: false });
  }),
);
// ダイアログを使わず直接入力/貼り付けした場合にも一覧を更新する。
$("openapi-path").addEventListener("change", () => {
  updateActiveOpenapiText();
  refreshOperationsList({ keepExcluded: false });
});

// ---------- DB接続設定（画面入力のみ。ファイル参照は行わず、実行時に裏で一時ファイル化する） ----------

function parsePort(text, label) {
  const n = parseInt(text, 10);
  if (!text || Number.isNaN(n)) {
    throw new Error(`${label} のポート番号は数値で入力してください: ${text || "(空欄)"}`);
  }
  return n;
}

function dbConfigEnabled() {
  return $("pg-enabled").checked || $("influx-enabled").checked;
}

function collectDbConfig() {
  const data = {};
  if ($("pg-enabled").checked) {
    data.postgres = {
      host: $("pg-host").value.trim(),
      port: parsePort($("pg-port").value.trim(), "PostgreSQL"),
      dbname: $("pg-dbname").value.trim(),
      user: $("pg-user").value.trim(),
      password: $("pg-password").value,
    };
  }
  if ($("influx-enabled").checked) {
    const influx = {
      host: $("influx-host").value.trim(),
      port: parsePort($("influx-port").value.trim(), "InfluxDB"),
      database: $("influx-database").value.trim(),
    };
    const username = $("influx-username").value.trim();
    const password = $("influx-password").value;
    if (username) influx.username = username;
    if (password) influx.password = password;
    data.influxdb = influx;
  }
  return data;
}

function updateActiveDbConfigText() {
  const parts = [];
  if ($("pg-enabled").checked) parts.push(`PostgreSQL(${$("pg-host").value.trim() || "?"})`);
  if ($("influx-enabled").checked) parts.push(`InfluxDB(${$("influx-host").value.trim() || "?"})`);
  const text = `DB接続設定: ${parts.length ? parts.join(" / ") : "未設定"}`;
  document.querySelectorAll(".status-dbconfig-text").forEach((el) => (el.textContent = text));
}

for (const id of ["pg-enabled", "pg-host", "influx-enabled", "influx-host"]) {
  $(id).addEventListener("input", updateActiveDbConfigText);
  $(id).addEventListener("change", updateActiveDbConfigText);
}

$("db-config-save").addEventListener("click", async () => {
  let data;
  try {
    data = collectDbConfig();
  } catch (e) {
    setDbConfigStatus(e.message, "error");
    return;
  }
  if (Object.keys(data).length === 0) {
    setDbConfigStatus("PostgreSQL/InfluxDBのいずれかを有効にしてください", "error");
    return;
  }
  const savePath = await save({ filters: [{ name: "JSON", extensions: ["json"] }], defaultPath: "config.json" });
  if (!savePath) return;
  try {
    await invoke("write_config_file", { path: savePath, data });
    setDbConfigStatus(`保存しました: ${savePath}`, "ok");
  } catch (e) {
    setDbConfigStatus(`保存に失敗しました: ${e}`, "error");
  }
});

$("db-config-check").addEventListener("click", async () => {
  let data;
  try {
    data = collectDbConfig();
  } catch (e) {
    setDbConfigStatus(e.message, "error");
    return;
  }
  if (Object.keys(data).length === 0) {
    setDbConfigStatus("PostgreSQL/InfluxDBのいずれかを有効にしてください", "error");
    return;
  }

  $("db-config-check").disabled = true;
  setDbConfigStatus("接続確認中...", null);
  let tempPath = null;
  try {
    tempPath = await invoke("write_config_file", { path: null, data });
    const result = await invoke("bridge_call", { command: "check_db_connectivity", args: { path: tempPath } });
    const ok = !result.includes("NG");
    setDbConfigStatus(result, ok ? "ok" : "error");
  } catch (e) {
    setDbConfigStatus(`接続確認に失敗しました: ${e}`, "error");
  } finally {
    if (tempPath) invoke("delete_file", { path: tempPath }).catch(() => {});
    $("db-config-check").disabled = false;
  }
});

// ---------- 出力先フォルダ / setup・teardown SQL ----------

$("browse-output-dir").addEventListener("click", () => browseDir("output-dir"));
$("browse-setup-sql").addEventListener("click", () =>
  browseFile("setup-sql-path", [{ name: "SQL", extensions: ["sql"] }]),
);
$("browse-teardown-sql").addEventListener("click", () =>
  browseFile("teardown-sql-path", [{ name: "SQL", extensions: ["sql"] }]),
);

// ---------- 認証設定（対象APIの中からログイン操作を選ぶだけでURL/メソッドを自動で使う） ----------

function authConfigEnabled() {
  return $("auth-enabled").checked;
}

function populateAuthLoginOpSelect() {
  const select = $("auth-login-op");
  const previous = select.value;
  select.innerHTML = "";

  if (lastOperations.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "「設定」画面でopenapi.jsonを選択すると一覧から選べます";
    select.appendChild(opt);
    return;
  }

  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "（選択してください）";
  select.appendChild(empty);

  for (const op of lastOperations) {
    const opt = document.createElement("option");
    opt.value = op.operationId;
    opt.textContent = `${op.method} ${op.path} (${op.operationId})`;
    select.appendChild(opt);
  }

  if (previous && lastOperations.some((op) => op.operationId === previous)) {
    select.value = previous;
  }
}

// ログイン操作を選ぶと、openapi.jsonのスキーマから分かる範囲でボディ/token_pathを自動入力する
// （example/defaultが無ければプロパティ名を仮の値にするだけ、token_pathはレスポンススキーマに
// それらしいキーが無ければ空のまま。あくまで下書きなので、埋まらない/違う場合は手入力する）。
async function applyLoginOperationHints() {
  const operationId = $("auth-login-op").value;
  const openapiPath = $("openapi-path").value.trim();
  if (!operationId || !openapiPath) return;

  let hints;
  try {
    hints = await invoke("bridge_call", { command: "login_operation_hints", args: { path: openapiPath, operation_id: operationId } });
  } catch {
    return; // 自動入力は失敗しても致命的ではないので無視する
  }

  const filled = [];
  if (hints.body && !$("auth-body").value.trim()) {
    $("auth-body").value = JSON.stringify(hints.body, null, 2);
    filled.push("ボディ");
  }
  if (hints.token_path && !$("auth-token-path").value.trim()) {
    $("auth-token-path").value = hints.token_path;
    filled.push("token_path");
  }
  const notes = [];
  if (filled.length > 0) {
    notes.push(`openapi.jsonから${filled.join("・")}を自動入力しました（内容を確認してください）`);
  }
  // token_pathはログイン操作の「レスポンス」側のスキーマから推測している。レスポンスに
  // スキーマが定義されていないopenapi.jsonも多く、その場合は何も起きず無言になってしまうため、
  // 推測できなかったこと自体を明示する（token_pathが自動で埋まらないのはバグではなく、
  // 単にopenapi.json側にレスポンスのスキーマが無いだけのことが多い）。
  if (!hints.token_path) {
    notes.push("token_pathはログイン操作のレスポンス定義から推測できませんでした。多くのAPIでは既定値（access_token）のままで動くので、まず空欄で試し、動かなければ実際のレスポンス形式に合わせて手入力してください");
  }
  if (notes.length > 0) {
    setAuthConfigStatus(notes.join(" / "), filled.length > 0 ? "ok" : null);
  }
}

$("auth-login-op").addEventListener("change", applyLoginOperationHints);

function collectAuthConfig() {
  const operationId = $("auth-login-op").value;
  const op = lastOperations.find((o) => o.operationId === operationId);
  if (!op) {
    throw new Error("ログイン操作を選択してください（対象APIの一覧から選べます）");
  }

  const bodyText = $("auth-body").value.trim();
  let body;
  if (bodyText) {
    try {
      body = JSON.parse(bodyText);
    } catch (e) {
      throw new Error(`ログインリクエストのボディがJSONとして解析できません: ${e.message}`);
    }
  }

  const data = { login_url: op.path, method: op.method };
  if (body !== undefined) data.body = body;
  const tokenPath = $("auth-token-path").value.trim();
  if (tokenPath) data.token_path = tokenPath;
  const headerName = $("auth-header-name").value.trim();
  if (headerName) data.header_name = headerName;
  const headerFormat = $("auth-header-format").value.trim();
  if (headerFormat) data.header_format = headerFormat;
  return data;
}

function setAuthConfigStatus(text, state) {
  const el = $("auth-config-status");
  el.textContent = text;
  el.classList.remove("error", "ok");
  if (state) el.classList.add(state);
}

$("auth-config-save").addEventListener("click", async () => {
  let data;
  try {
    data = collectAuthConfig();
  } catch (e) {
    setAuthConfigStatus(e.message, "error");
    return;
  }
  const savePath = await save({ filters: [{ name: "YAML/JSON", extensions: ["yaml", "yml", "json"] }], defaultPath: "auth_config.yaml" });
  if (!savePath) return;
  try {
    await invoke("write_config_file", { path: savePath, data });
    setAuthConfigStatus(`保存しました: ${savePath}`, "ok");
  } catch (e) {
    setAuthConfigStatus(`保存に失敗しました: ${e}`, "error");
  }
});

// ---------- 対象APIチェックリスト ----------

let lastOperations = [];

async function refreshOperationsList({ keepExcluded }) {
  const path = $("openapi-path").value.trim();
  const container = $("operations-list");
  if (!path) {
    container.innerHTML = '<div class="op-empty">「設定」画面でopenapi.jsonを選択すると一覧が表示されます</div>';
    lastOperations = [];
    populateAuthLoginOpSelect();
    return;
  }

  let ops;
  try {
    ops = await invoke("bridge_call", { command: "list_operations", args: { path } });
  } catch (e) {
    container.innerHTML = `<div class="op-empty">読み込みに失敗しました: ${e}</div>`;
    lastOperations = [];
    populateAuthLoginOpSelect();
    return;
  }

  lastOperations = ops || [];
  populateAuthLoginOpSelect();
  if (lastOperations.length === 0) {
    container.innerHTML = '<div class="op-empty">operationが見つかりませんでした</div>';
    return;
  }

  const excluded = keepExcluded
    ? new Set(
        (settings.gen_excluded_operations || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      )
    : new Set();

  container.innerHTML = "";
  for (const op of lastOperations) {
    const row = document.createElement("label");
    row.className = "op-item";
    const checked = !excluded.has(op.operationId);
    row.innerHTML = `
      <span class="op-row1">
        <input type="checkbox" data-op-id="${op.operationId}" ${checked ? "checked" : ""}/>
        <span class="op-method">${op.method}</span>
      </span>
      <span class="op-path">${op.path}</span>
      <span class="op-id">${op.operationId}</span>`;
    container.appendChild(row);
  }

  await maybeAutofillBaseUrl(path);
}

async function maybeAutofillBaseUrl(path) {
  if ($("base-url").value.trim()) return;
  try {
    const url = await invoke("bridge_call", { command: "servers_url", args: { path } });
    if (url) $("base-url").value = url;
  } catch {
    // 自動入力は失敗しても致命的ではないので無視する
  }
}

function getUncheckedOperationIds() {
  return Array.from(document.querySelectorAll("#operations-list input[type=checkbox]"))
    .filter((el) => !el.checked)
    .map((el) => el.dataset.opId);
}

$("ops-select-all").addEventListener("click", () => {
  document.querySelectorAll("#operations-list input[type=checkbox]").forEach((el) => (el.checked = true));
});
$("ops-select-none").addEventListener("click", () => {
  document.querySelectorAll("#operations-list input[type=checkbox]").forEach((el) => (el.checked = false));
});

// ---------- パス組み立て ----------

function joinPath(dir, name) {
  if (!dir) return name;
  return /[\\/]$/.test(dir) ? `${dir}${name}` : `${dir}\\${name}`;
}

function dirName(path) {
  const idx = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return idx >= 0 ? path.slice(0, idx) : "";
}

// ---------- 汎用: 1本のスクリプトを実行してログ欄に流し込む（DB準備の生成系スクリプト用） ----------
// テスト生成・実行/DBシナリオの「2段階・キャンセル可能」な実行とは別に、単発で終わる
// 生成スクリプト（generate_mapping.py等）を使い回すための軽量な仕組み。同じ
// run_script/proc-line/proc-doneイベントを共有するため、下のリスナーでrunIdを見て振り分ける。

const simpleRuns = new Map();

function runSimpleScript(script, args, { logEl, statusEl, doneMessage } = {}) {
  return new Promise((resolve) => {
    const runId = `simple-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    if (logEl) {
      logEl.hidden = false;
      logEl.textContent = "";
    }
    if (statusEl) {
      statusEl.textContent = "実行中...";
      statusEl.classList.remove("error", "ok");
    }
    simpleRuns.set(runId, { logEl, statusEl, doneMessage, resolve });
    invoke("run_script", { runId, script, args });
  });
}

// ---------- DB準備（setup.sql/teardown.sql・mapping.yaml・シナリオYAMLの生成） ----------

function showDbPrepError(message) {
  const el = $("dbprep-error");
  el.textContent = message;
  el.hidden = false;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideDbPrepError() {
  $("dbprep-error").hidden = true;
}

async function ensureDirForOutput(outputPath, openapiPath) {
  const dir = dirName(outputPath) || dirName(openapiPath);
  if (!dir) return;
  await invoke("ensure_output_dir", { path: dir });
}

$("dbprep-goto-settings").addEventListener("click", () => showPage("settings"));
$("dbprep-browse-sql-output-dir").addEventListener("click", () => browseDir("dbprep-sql-output-dir"));
$("dbprep-browse-mapping-output").addEventListener("click", () =>
  browseSaveFile("dbprep-mapping-output", [{ name: "YAML", extensions: ["yaml", "yml"] }], "mapping.yaml"),
);
$("dbprep-browse-scenario-mapping").addEventListener("click", () =>
  browseFile("dbprep-scenario-mapping-path", [{ name: "YAML", extensions: ["yaml", "yml"] }]),
);
$("dbprep-browse-scenario-output").addEventListener("click", () =>
  browseSaveFile("dbprep-scenario-output", [{ name: "YAML", extensions: ["yaml", "yml"] }], "scenarios.yaml"),
);

$("dbprep-gen-sql-button").addEventListener("click", async () => {
  hideDbPrepError();
  if (!$("pg-enabled").checked) {
    showDbPrepError("PostgreSQLのDB接続設定が必要です（「設定」画面。setup.sql/teardown.sqlの生成はPostgreSQLのみ対応）");
    return;
  }
  let dbConfigData;
  try {
    dbConfigData = collectDbConfig();
  } catch (e) {
    showDbPrepError(e.message);
    return;
  }

  const openapiPath = $("openapi-path").value.trim();
  const outputDir = $("dbprep-sql-output-dir").value.trim() || dirName(openapiPath);
  try {
    await invoke("ensure_output_dir", { path: outputDir });
  } catch (e) {
    showDbPrepError(String(e));
    return;
  }

  let configPath;
  try {
    configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
  } catch (e) {
    showDbPrepError(`DB接続設定の準備に失敗しました: ${e}`);
    return;
  }

  await persistSettings();

  const setupOutput = joinPath(outputDir, "setup.sql");
  const teardownOutput = joinPath(outputDir, "teardown.sql");
  const args = ["--config", configPath, "--setup-output", setupOutput, "--teardown-output", teardownOutput];
  const schema = $("pg-schema").value.trim();
  if (schema) args.push("--schema", schema);
  const tables = $("dbprep-sql-tables").value.trim();
  if (tables) args.push("--tables", tables);

  $("dbprep-gen-sql-button").disabled = true;
  const code = await runSimpleScript("runner/generate_setup_sql.py", args, {
    logEl: $("dbprep-sql-log"),
    statusEl: $("dbprep-sql-status"),
    doneMessage: `生成しました: ${setupOutput} / ${teardownOutput}`,
  });
  $("dbprep-gen-sql-button").disabled = false;
  invoke("delete_file", { path: configPath }).catch(() => {});
  if (code === 0) {
    // 生成したファイルを「テスト生成・実行」の試験前SQL/試験後SQLへそのまま連携する。
    $("setup-sql-path").value = setupOutput;
    $("teardown-sql-path").value = teardownOutput;
  }
});

$("dbprep-gen-mapping-button").addEventListener("click", async () => {
  hideDbPrepError();
  const openapiPath = $("openapi-path").value.trim();
  if (!openapiPath) {
    showDbPrepError("openapi.json を選択してください（「設定」画面）");
    return;
  }
  if (!$("pg-enabled").checked) {
    showDbPrepError("PostgreSQLのDB接続設定が必要です（「設定」画面。mapping.yamlの生成はPostgreSQLのみ対応）");
    return;
  }
  let dbConfigData;
  try {
    dbConfigData = collectDbConfig();
  } catch (e) {
    showDbPrepError(e.message);
    return;
  }

  const outputPath = $("dbprep-mapping-output").value.trim() || joinPath(dirName(openapiPath), "mapping.yaml");
  try {
    await ensureDirForOutput(outputPath, openapiPath);
  } catch (e) {
    showDbPrepError(String(e));
    return;
  }

  let configPath;
  try {
    configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
  } catch (e) {
    showDbPrepError(`DB接続設定の準備に失敗しました: ${e}`);
    return;
  }

  await persistSettings();

  const args = [openapiPath, "--config", configPath, "-o", outputPath];
  const schema = $("pg-schema").value.trim();
  if (schema) args.push("--schema", schema);

  $("dbprep-gen-mapping-button").disabled = true;
  const code = await runSimpleScript("runner/generate_mapping.py", args, {
    logEl: $("dbprep-mapping-log"),
    statusEl: $("dbprep-mapping-status"),
    doneMessage: `生成しました: ${outputPath}（確信度の低い項目は必ず確認してください）`,
  });
  $("dbprep-gen-mapping-button").disabled = false;
  invoke("delete_file", { path: configPath }).catch(() => {});
  if (code === 0) {
    // 次のステップ（シナリオYAML生成）へそのまま連携する。
    $("dbprep-scenario-mapping-path").value = outputPath;
  }
});

$("dbprep-gen-scenario-button").addEventListener("click", async () => {
  hideDbPrepError();
  const openapiPath = $("openapi-path").value.trim();
  if (!openapiPath) {
    showDbPrepError("openapi.json を選択してください（「設定」画面）");
    return;
  }
  const mappingPath = $("dbprep-scenario-mapping-path").value.trim();
  if (!mappingPath) {
    showDbPrepError("APIとDBテーブルの対応表（mapping.yaml）を指定してください（上の手順2で生成するか、既存のファイルを選んでください）");
    return;
  }

  const outputPath = $("dbprep-scenario-output").value.trim() || joinPath(dirName(openapiPath), "scenarios.yaml");
  try {
    await ensureDirForOutput(outputPath, openapiPath);
  } catch (e) {
    showDbPrepError(String(e));
    return;
  }

  await persistSettings();

  const args = [openapiPath, mappingPath, "-o", outputPath];
  $("dbprep-gen-scenario-button").disabled = true;
  const code = await runSimpleScript("runner/generate_db_scenarios.py", args, {
    logEl: $("dbprep-scenario-log"),
    statusEl: $("dbprep-scenario-status"),
    doneMessage: `生成しました: ${outputPath}（where/columns等は必ず確認・修正してください）`,
  });
  $("dbprep-gen-scenario-button").disabled = false;
  if (code === 0) {
    // 「DBシナリオ」タブへそのまま連携する。
    $("dbscenario-path").value = outputPath;
  }
});

// ---------- DBシナリオ（生成したシナリオYAMLの実行） ----------

let dbScenarioRunId = null;
let dbScenarioResultPath = null;
let dbScenarioTempDbConfigPath = null;
let dbScenarioTempAuthConfigPath = null;

function showDbScenarioError(message) {
  const el = $("dbscenario-error");
  el.textContent = message;
  el.hidden = false;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideDbScenarioError() {
  $("dbscenario-error").hidden = true;
}

function setDbScenarioStatus(text, state) {
  const el = $("dbscenario-status");
  el.textContent = text;
  el.dataset.state = state || "";
}

function appendDbScenarioLog(line) {
  const log = $("dbscenario-log");
  log.textContent += (log.textContent ? "\n" : "") + line;
  log.scrollTop = log.scrollHeight;
}

function finishDbScenarioRunUi(code) {
  const meaning = { 0: "OK：全シナリオ成功", 1: "NG：1件以上失敗", 3: "ERROR：実行エラー" }[code] || `終了コード ${code}`;
  const state = { 0: "ok", 1: "ng" }[code] || "ng";
  setDbScenarioStatus(meaning, state);
  $("dbscenario-run-button").disabled = false;
  $("dbscenario-cancel-button").disabled = true;
  if (code === 0 && dbScenarioResultPath) {
    $("dbscenario-open-result-button").disabled = false;
  }
}

$("dbscenario-goto-settings").addEventListener("click", () => showPage("settings"));
$("dbscenario-browse").addEventListener("click", () =>
  browseFile("dbscenario-path", [{ name: "YAML", extensions: ["yaml", "yml"] }]),
);
$("dbscenario-browse-report").addEventListener("click", () =>
  browseSaveFile("dbscenario-report-output", [{ name: "Excel", extensions: ["xlsx"] }], "DBシナリオ結果.xlsx"),
);

$("dbscenario-run-button").addEventListener("click", async () => {
  hideDbScenarioError();

  const openapiPath = $("openapi-path").value.trim();
  const baseUrl = $("base-url").value.trim();
  const scenarioPath = $("dbscenario-path").value.trim();

  if (!openapiPath) {
    showDbScenarioError("openapi.json を選択してください（「設定」画面）");
    return;
  }
  if (!baseUrl) {
    showDbScenarioError("Base URL を入力してください（「設定」画面）");
    return;
  }
  if (!scenarioPath) {
    showDbScenarioError("DB検証シナリオファイル（scenarios.yaml）を選択してください（「DB準備」タブで生成できます）");
    return;
  }
  if (!dbConfigEnabled()) {
    showDbScenarioError("DB接続設定（「設定」画面）が必要です");
    return;
  }

  let dbConfigData;
  try {
    dbConfigData = collectDbConfig();
  } catch (e) {
    showDbScenarioError(e.message);
    return;
  }
  let configPath;
  try {
    configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
  } catch (e) {
    showDbScenarioError(`DB接続設定の準備に失敗しました: ${e}`);
    return;
  }
  dbScenarioTempDbConfigPath = configPath;

  let authConfigPath = "";
  if (authConfigEnabled()) {
    let authConfigData;
    try {
      authConfigData = collectAuthConfig();
    } catch (e) {
      showDbScenarioError(e.message);
      invoke("delete_file", { path: configPath }).catch(() => {});
      dbScenarioTempDbConfigPath = null;
      return;
    }
    try {
      authConfigPath = await invoke("write_config_file", { path: null, data: authConfigData });
    } catch (e) {
      showDbScenarioError(`認証設定の準備に失敗しました: ${e}`);
      invoke("delete_file", { path: configPath }).catch(() => {});
      dbScenarioTempDbConfigPath = null;
      return;
    }
  }
  dbScenarioTempAuthConfigPath = authConfigPath || null;

  await persistSettings();

  const reportOutput = $("dbscenario-report-output").value.trim();
  // ヘルスチェックは「設定」画面のAPI疎通確認で独立して行える運用のため、常にスキップする。
  const args = [scenarioPath, openapiPath, "--base-url", baseUrl, "--config", configPath, "--skip-health-check"];
  if (authConfigPath) args.push("--auth-config", authConfigPath);
  if (reportOutput) args.push("--report-output", reportOutput);
  if ($("dbscenario-dry-run").checked) args.push("--dry-run");

  dbScenarioRunId = `dbscenario-${Date.now()}`;
  dbScenarioResultPath = reportOutput || null;
  $("dbscenario-log").textContent = "";
  $("dbscenario-run-button").disabled = true;
  $("dbscenario-cancel-button").disabled = false;
  $("dbscenario-open-result-button").disabled = true;
  setDbScenarioStatus("実行中...", "running");

  invoke("run_script", { runId: dbScenarioRunId, script: "runner/db_scenario_runner.py", args });
});

$("dbscenario-cancel-button").addEventListener("click", async () => {
  if (dbScenarioRunId) await invoke("cancel_script", { runId: dbScenarioRunId });
});

$("dbscenario-open-result-button").addEventListener("click", async () => {
  if (dbScenarioResultPath) {
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(dbScenarioResultPath).catch(() => {});
  }
});

// ---------- 実行（生成→実行の2段階） ----------

let currentRunId = null;
let pendingSecondStage = null;
let currentResultPath = null;
let tempDbConfigPath = null;
let tempAuthConfigPath = null;
let progressTotal = 0;
let progressDone = 0;

function appendLog(line) {
  const log = $("run-log");
  log.textContent += (log.textContent ? "\n" : "") + line;
  log.scrollTop = log.scrollHeight;
  feedProgress(line);
}

function feedProgress(line) {
  const totalMatch = line.match(/(?:試験ケース数|シナリオ数)[：:]\s*(\d+)\s*件/);
  if (totalMatch) {
    progressTotal = parseInt(totalMatch[1], 10);
    progressDone = 0;
    updateProgressBar();
    return;
  }
  if (/^\s*\[(OK|NG|WARNING|SKIP)\]/.test(line)) {
    progressDone += 1;
    updateProgressBar();
  }
}

function updateProgressBar() {
  const pct = progressTotal > 0 ? Math.max(0, Math.min(100, Math.round((progressDone / progressTotal) * 100))) : 0;
  $("run-progress-bar").style.width = `${pct}%`;
}

function setStatus(text, state) {
  const el = $("run-status");
  el.textContent = text;
  el.dataset.state = state || "";
}

function showGenError(message) {
  const el = $("gen-error");
  el.textContent = message;
  el.hidden = false;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideGenError() {
  $("gen-error").hidden = true;
}

function setDbConfigStatus(text, state) {
  const el = $("db-config-status");
  el.textContent = text;
  el.classList.remove("error", "ok");
  if (state) el.classList.add(state);
}

function startRunUi() {
  $("run-log").textContent = "";
  progressTotal = 0;
  progressDone = 0;
  updateProgressBar();
  $("run-button").disabled = true;
  $("cancel-button").disabled = false;
  $("open-result-button").disabled = true;
  setStatus("実行中...", "running");
}

function finishRunUi(code) {
  const meaning =
    { 0: "OK：全ケース成功", 1: "NG：1件以上失敗", 2: "WARNING：1件以上警告（応答時間超過）", 3: "ERROR：実行エラー", 4: "ERROR：設定エラー" }[
      code
    ] || `終了コード ${code}`;
  const state = { 0: "ok", 1: "ng", 2: "warn" }[code] || "ng";
  setStatus(meaning, state);
  $("run-button").disabled = false;
  $("cancel-button").disabled = true;
  if (code === 0) {
    $("run-progress-bar").style.width = "100%";
    $("open-result-button").disabled = false;
  }
}

$("run-button").addEventListener("click", async () => {
  hideGenError();

  const openapiPath = $("openapi-path").value.trim();
  const baseUrl = $("base-url").value.trim();
  if (!openapiPath) {
    showGenError("openapi.json を選択してください（「設定」画面）");
    return;
  }
  if (!baseUrl) {
    showGenError("Base URL を入力してください（「設定」画面）");
    return;
  }

  const unchecked = getUncheckedOperationIds();
  if (lastOperations.length > 0 && unchecked.length === lastOperations.length) {
    showGenError("対象APIを少なくとも1つ選択してください（サイドバーの「対象API」）");
    return;
  }

  const setupPath = $("setup-sql-path").value.trim();
  const teardownPath = $("teardown-sql-path").value.trim();
  if ((setupPath || teardownPath) && !dbConfigEnabled()) {
    showGenError("試験前SQL または 試験後SQL を指定する場合は DB接続設定（「設定」画面）が必要です");
    return;
  }

  const outputDir = $("output-dir").value.trim() || dirName(openapiPath);
  try {
    await invoke("ensure_output_dir", { path: outputDir });
  } catch (e) {
    showGenError(`${e}（「2. 実行設定」の出力先フォルダを確認してください）`);
    return;
  }

  let configPath = "";
  if (dbConfigEnabled()) {
    let dbConfigData;
    try {
      dbConfigData = collectDbConfig();
    } catch (e) {
      showGenError(e.message);
      return;
    }
    try {
      configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
    } catch (e) {
      showGenError(`DB接続設定の準備に失敗しました: ${e}`);
      return;
    }
  }
  tempDbConfigPath = configPath || null;

  let authConfigPath = "";
  if (authConfigEnabled()) {
    let authConfigData;
    try {
      authConfigData = collectAuthConfig();
    } catch (e) {
      showGenError(e.message);
      return;
    }
    try {
      authConfigPath = await invoke("write_config_file", { path: null, data: authConfigData });
    } catch (e) {
      showGenError(`認証設定の準備に失敗しました: ${e}`);
      return;
    }
  }
  tempAuthConfigPath = authConfigPath || null;

  await persistSettings();

  const specPath = joinPath(outputDir, "試験仕様.xlsx");
  const casesPath = joinPath(outputDir, "test_cases.json");
  const resultPath = joinPath(outputDir, "試験仕様_result.xlsx");

  const genArgs = [openapiPath, "-o", casesPath, "--excel-output", specPath];
  if (unchecked.length > 0) genArgs.push("--exclude-ops", unchecked.join(","));

  // ヘルスチェック（疎通確認）は「ヘルスチェック」画面で独立して行える運用にしたため、
  // 試験実行時は常にスキップする。
  const runArgs = [specPath, openapiPath, "--base-url", baseUrl, "--output", resultPath, "--skip-health-check"];
  if (authConfigPath) runArgs.push("--auth-config", authConfigPath);
  if (configPath) runArgs.push("--config", configPath);
  if (setupPath) runArgs.push("--setup", setupPath);
  if (teardownPath) runArgs.push("--teardown", teardownPath);
  if ($("full-body").checked) runArgs.push("--full-body");
  if ($("fail-fast").checked) runArgs.push("--fail-fast");
  if ($("dry-run").checked) runArgs.push("--dry-run");

  currentRunId = `gen-${Date.now()}`;
  currentResultPath = resultPath;
  startRunUi();
  pendingSecondStage = { script: "runner/runner.py", args: runArgs };

  invoke("run_script", { runId: currentRunId, script: "src/cli.py", args: genArgs });
});

$("cancel-button").addEventListener("click", async () => {
  if (currentRunId) await invoke("cancel_script", { runId: currentRunId });
});

$("open-result-button").addEventListener("click", async () => {
  if (currentResultPath) {
    // 結果を開く操作はOS標準の関連付けアプリで開く。opener権限を使う。
    const { openPath } = await import("@tauri-apps/plugin-opener");
    await openPath(currentResultPath).catch(() => {});
  }
});

listen("proc-line", (event) => {
  const { runId, line } = event.payload;
  if (runId === currentRunId) {
    appendLog(line);
    return;
  }
  if (runId === dbScenarioRunId) {
    appendDbScenarioLog(line);
    return;
  }
  const simple = simpleRuns.get(runId);
  if (simple && simple.logEl) {
    simple.logEl.textContent += (simple.logEl.textContent ? "\n" : "") + line;
    simple.logEl.scrollTop = simple.logEl.scrollHeight;
  }
});

listen("proc-done", async (event) => {
  const { runId, code } = event.payload;

  const simple = simpleRuns.get(runId);
  if (simple) {
    simpleRuns.delete(runId);
    if (simple.statusEl) {
      if (code === 0) {
        simple.statusEl.textContent = simple.doneMessage || "完了しました";
        simple.statusEl.classList.add("ok");
      } else {
        simple.statusEl.textContent = `失敗しました（終了コード ${code}）。ログを確認してください`;
        simple.statusEl.classList.add("error");
      }
    }
    simple.resolve(code);
    return;
  }

  if (runId === dbScenarioRunId) {
    finishDbScenarioRunUi(code);
    if (dbScenarioTempDbConfigPath) {
      invoke("delete_file", { path: dbScenarioTempDbConfigPath }).catch(() => {});
      dbScenarioTempDbConfigPath = null;
    }
    if (dbScenarioTempAuthConfigPath) {
      invoke("delete_file", { path: dbScenarioTempAuthConfigPath }).catch(() => {});
      dbScenarioTempAuthConfigPath = null;
    }
    return;
  }

  if (runId !== currentRunId) return;

  if (pendingSecondStage) {
    const stage = pendingSecondStage;
    pendingSecondStage = null;
    if (code !== 0) {
      appendLog(`[ERROR] テスト仕様の生成に失敗しました（終了コード ${code}）`);
      finishRunUi(code);
      return;
    }
    appendLog("");
    invoke("run_script", { runId: currentRunId, script: stage.script, args: stage.args });
    return;
  }

  finishRunUi(code);
  if (tempDbConfigPath) {
    invoke("delete_file", { path: tempDbConfigPath }).catch(() => {});
    tempDbConfigPath = null;
  }
  if (tempAuthConfigPath) {
    invoke("delete_file", { path: tempAuthConfigPath }).catch(() => {});
    tempAuthConfigPath = null;
  }
});

// ---------- 初期化 ----------

loadSettingsIntoForm();
