import { applyComparisonRules, comparisonRulesFromSchema, renderComparisonRules } from "./comparison-rules.js";
import { invoke, listen, open, save, openPath } from "./runtime.js";
import { buildProjectData } from "./project-config.js";
import { COPILOT_OPENAPI_PROMPT } from "./copilot-openapi-prompt.js";
import { createWorkflowClient } from "./workflow-client.js";
import { builderNodeToSchema, renderSchemaBuilder, schemaToBuilderNode } from "./schema-builder.js";
import { applyPresenceRules, presenceRulesFromSchema, renderPresenceRules } from "./presence-rules.js";
import { initDbScenarioEditor } from "./db-scenario-editor.js";

const workflowClient = createWorkflowClient({ invoke, listen });
const dbScenarioEditor = initDbScenarioEditor({
  invoke,
  saveDialog: save,
  onSaved: async () => persistSettings(),
});

function $(id) {
  return document.getElementById(id);
}

// ---------- 設定の読み込み/保存（PySide6版と同じ設定ファイルを共有） ----------

let settings = {};

export async function loadRuntimeDiagnosis() {
  const status = $("runtime-status");
  try {
    const diagnosis = await invoke("diagnose_runtime");
    const scriptsReady = diagnosis.workflowAvailable && diagnosis.generatorAvailable && diagnosis.runnerAvailable;
    if (diagnosis.pythonAvailable && scriptsReady) {
      const pythonSource = diagnosis.pythonBundled ? "同梱" : "PATH";
      status.textContent = `実行環境: ${diagnosis.pythonVersion || "Python"}（${pythonSource}）を確認しました`;
      status.classList.add("ok");
      return;
    }
    status.textContent = "実行環境を確認できません。Pythonとアプリの同梱ファイルを確認してください。";
    status.classList.add("error");
  } catch {
    status.textContent = "実行環境を確認できません。Pythonとアプリの同梱ファイルを確認してください。";
    status.classList.add("error");
  }
}

export async function loadAppVersion() {
  const version = $("app-version");
  try {
    const value = await invoke("app_version");
    version.textContent = typeof value === "string" && value ? `v${value}` : "バージョン不明";
  } catch {
    version.textContent = "バージョン不明";
  }
}

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
  $("no-normal").checked = !!settings.gen_no_normal;
  $("no-abnormal").checked = !!settings.gen_no_abnormal;
  $("parallel").value = settings.gen_parallel || "";
  $("cookie-jar").checked = !!settings.gen_cookie_jar;
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
  syncDbConfigFieldsEnabled();

  $("auth-enabled").checked = !!settings.auth_enabled;
  $("auth-token-path").value = settings.auth_token_path || "";
  $("auth-header-name").value = settings.auth_header_name || "";
  $("auth-header-format").value = settings.auth_header_format || "";
  // ボディは認証情報を含みうるため、設定ファイルに平文保存しない（起動時は毎回未入力）
  syncAuthFieldsEnabled();

  $("dbprep-sql-tables").value = settings.dbprep_sql_tables || "";
  $("dbprep-sql-output-dir").value = settings.dbprep_sql_output_dir || "";
  $("dbscenario-path").value = settings.dbscenario_path || "";
  $("dbscenario-dry-run").checked = !!settings.dbscenario_dry_run;
  $("dbscenario-cookie-jar").checked = !!settings.dbscenario_cookie_jar;

  updateActiveOpenapiText();
  updateActiveBaseUrlText();
  updateActiveDbConfigText();

  if (Object.keys(settings).length) {
    settingsNotice("前回の設定を復元しました。DBパスワードと認証用の入力値は再確認してください。API定義・DB対応は保存済みファイルから読み込みます。");
  }
  await refreshOperationsList({ keepExcluded: true });
  await dbScenarioEditor.restoreSaved();
  // ログイン操作の選択はoperation一覧に依存するため、一覧更新後に復元する。
  // value を直接書き換えても change イベントは発火しないため、ボディ/token_pathの
  // 自動入力を明示的に呼び直す（呼ばないと「選択済みなのに毎回空欄」になる）。
  if (settings.auth_login_op) {
    $("auth-login-op").value = settings.auth_login_op;
    await applyLoginOperationHints();
  }
}

function settingsNotice(message) {
  $("settings-status").textContent = message;
}

$("settings-save").addEventListener("click", async () => {
  const button = $("settings-save");
  button.disabled = true;
  try {
    await persistSettings();
    updateActiveBaseUrlText();
    updateActiveDbConfigText();
  } catch {
    settingsNotice("設定を保存できませんでした。保存先の空き容量と書き込み権限を確認してください。");
  } finally {
    button.disabled = false;
  }
});

async function persistSettings() {
  settings.shared_openapi_path = $("openapi-path").value.trim();
  settings.gen_output_dir = $("output-dir").value.trim();
  settings.gen_base_url = $("base-url").value.trim();
  settings.gen_setup_path = $("setup-sql-path").value.trim();
  settings.gen_teardown_path = $("teardown-sql-path").value.trim();
  settings.gen_dry_run = $("dry-run").checked;
  settings.gen_full_body = $("full-body").checked;
  settings.gen_fail_fast = $("fail-fast").checked;
  settings.gen_no_normal = $("no-normal").checked;
  settings.gen_no_abnormal = $("no-abnormal").checked;
  settings.gen_parallel = $("parallel").value.trim();
  settings.gen_cookie_jar = $("cookie-jar").checked;
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
  settings.dbscenario_path = $("dbscenario-path").value.trim();
  settings.dbscenario_dry_run = $("dbscenario-dry-run").checked;
  settings.dbscenario_cookie_jar = $("dbscenario-cookie-jar").checked;

  await invoke("save_settings", { data: settings });
  settingsNotice("このPCに設定を保存しました。再起動後、DBパスワードと認証用の入力値は再確認してください。");
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

function setProjectStatus(text, state) {
  const status = $("project-status");
  status.textContent = text;
  status.classList.remove("error", "ok");
  if (state) status.classList.add(state);
}

// ---------- サイドバーナビゲーション ----------

function showPage(pageId, activeTab = null) {
  document.querySelectorAll("#top-nav .tab[data-page]").forEach((el) => {
    const active = activeTab ? el === activeTab : el.dataset.page === pageId;
    el.classList.toggle("active", active);
    if (el.dataset.step) {
      if (active) el.setAttribute("aria-current", "step");
      else el.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll(".page").forEach((el) => el.classList.toggle("active", el.id === `page-${pageId}`));
}

for (const tab of document.querySelectorAll("#top-nav .tab[data-page]")) {
  tab.addEventListener("click", () => {
    showPage(tab.dataset.page, tab);
    if (tab.dataset.target) {
      document.getElementById(tab.dataset.target)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
    }
  });
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

let pendingCopilotDraft = null;

function setCopilotStatus(message, state) {
  const status = $("copilot-status");
  status.textContent = message;
  status.classList.remove("error", "ok");
  if (state) status.classList.add(state);
}

$("copilot-prompt-copy").addEventListener("click", async () => {
  try {
    await window.navigator.clipboard.writeText(COPILOT_OPENAPI_PROMPT);
    setCopilotStatus("Copilot用の依頼文をコピーしました。VS CodeのCopilot Chatへ貼り付けてください。", "ok");
  } catch {
    setCopilotStatus("コピーできませんでした。クリップボードの利用権限を確認してください。", "error");
  }
});

$("copilot-draft-import").addEventListener("click", async () => {
  pendingCopilotDraft = null;
  $("copilot-draft-reviewed").checked = false;
  $("copilot-draft-apply").disabled = true;
  let path;
  try {
    path = await open({ multiple: false, filters: [{ name: "OpenAPI JSON", extensions: ["json"] }] });
    if (!path) return;
    const result = await invoke("bridge_call", { command: "validate_openapi", args: { path } });
    const count = /^OK（operation数: (\d+)）$/.exec(result)?.[1];
    if (!count || Number(count) === 0) {
      setCopilotStatus(result.startsWith("NG:") ? result : "試験できるAPI操作がありません。下書きのpathsを確認してください。", "error");
      return;
    }
    const operations = await invoke("bridge_call", { command: "list_operations", args: { path } });
    if (!Array.isArray(operations) || operations.length !== Number(count)
      || new Set(operations.map((operation) => operation.operationId)).size !== operations.length) {
      setCopilotStatus("operationIdの欠落または重複があります。下書きの全操作に一意のoperationIdを付けてください。", "error");
      return;
    }
    pendingCopilotDraft = path;
    setCopilotStatus(`${count}件のAPI操作を読み込みました。openapi.review.mdと下書きを確認してください。`, "ok");
  } catch {
    setCopilotStatus("下書きを読み込めませんでした。JSONファイルの内容を確認してください。", "error");
  }
});

$("copilot-draft-reviewed").addEventListener("change", () => {
  $("copilot-draft-apply").disabled = !pendingCopilotDraft || !$("copilot-draft-reviewed").checked;
});

$("copilot-draft-apply").addEventListener("click", async () => {
  if (!pendingCopilotDraft || !$("copilot-draft-reviewed").checked) return;
  $("openapi-path").value = pendingCopilotDraft;
  updateActiveOpenapiText();
  await refreshOperationsList({ keepExcluded: false });
  setCopilotStatus("確認済み下書きを試験対象に設定しました。Base URLと対象APIを確認してください。", "ok");
});

// ---------- DB接続設定（画面入力のみ。ファイル参照は行わず、実行時に裏で一時ファイル化する） ----------

export function parsePort(text, label) {
  if (!text || !/^\d+$/.test(text)) {
    throw new Error(`${label} のポート番号は数値で入力してください: ${text || "(空欄)"}`);
  }
  return parseInt(text, 10);
}

export function dbConfigEnabled() {
  return $("pg-enabled").checked || $("influx-enabled").checked;
}

export function requireField(value, label) {
  if (!value) {
    throw new Error(`${label} を入力してください`);
  }
  return value;
}

export function collectDbConfig() {
  const data = {};
  if ($("pg-enabled").checked) {
    data.postgres = {
      host: requireField($("pg-host").value.trim(), "PostgreSQLのhost"),
      port: parsePort($("pg-port").value.trim(), "PostgreSQL"),
      dbname: requireField($("pg-dbname").value.trim(), "PostgreSQLのdbname"),
      user: requireField($("pg-user").value.trim(), "PostgreSQLのuser"),
      password: $("pg-password").value,
    };
  }
  if ($("influx-enabled").checked) {
    const influx = {
      host: requireField($("influx-host").value.trim(), "InfluxDBのhost"),
      port: parsePort($("influx-port").value.trim(), "InfluxDB"),
      database: requireField($("influx-database").value.trim(), "InfluxDBのdatabase"),
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

const PG_DEPENDENT_FIELD_IDS = ["pg-host", "pg-port", "pg-dbname", "pg-schema", "pg-user", "pg-password"];
const INFLUX_DEPENDENT_FIELD_IDS = ["influx-host", "influx-port", "influx-database", "influx-username", "influx-password"];

function syncDbConfigFieldsEnabled() {
  const pgEnabled = $("pg-enabled").checked;
  for (const id of PG_DEPENDENT_FIELD_IDS) $(id).disabled = !pgEnabled;
  const influxEnabled = $("influx-enabled").checked;
  for (const id of INFLUX_DEPENDENT_FIELD_IDS) $(id).disabled = !influxEnabled;
}

$("pg-enabled").addEventListener("change", syncDbConfigFieldsEnabled);
$("influx-enabled").addEventListener("change", syncDbConfigFieldsEnabled);

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

const AUTH_DEPENDENT_FIELD_IDS = [
  "auth-login-op",
  "auth-body",
  "auth-profiles",
  "auth-token-path",
  "auth-header-name",
  "auth-header-format",
  "auth-config-save",
];

function syncAuthFieldsEnabled() {
  const enabled = authConfigEnabled();
  for (const id of AUTH_DEPENDENT_FIELD_IDS) {
    $(id).disabled = !enabled;
  }
}

$("auth-enabled").addEventListener("change", syncAuthFieldsEnabled);

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

export function parseAuthProfiles(text) {
  if (!text.trim()) return null;

  let profiles;
  try {
    profiles = JSON.parse(text);
  } catch {
    throw new Error("役割別ログイン情報がJSONとして解析できません。入力内容を確認してください");
  }
  if (!profiles || Array.isArray(profiles) || typeof profiles !== "object") {
    throw new Error("役割別ログイン情報はプロファイル名とログインボディのJSONオブジェクトで指定してください");
  }
  for (const [name, body] of Object.entries(profiles)) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$/.test(name)) {
      throw new Error("プロファイル名は英数字で始まる英数字・ドット・ハイフン・アンダースコアにしてください");
    }
    if (!body || Array.isArray(body) || typeof body !== "object") {
      throw new Error(`プロファイル「${name}」のログインボディはJSONオブジェクトで指定してください`);
    }
  }
  return profiles;
}

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
      throw new Error(`ログインリクエストのボディがJSONとして解析できません: ${e.message}`, { cause: e });
    }
  }

  const data = { login_url: op.path, method: op.method };
  if (body !== undefined) data.body = body;
  const authProfiles = parseAuthProfiles($("auth-profiles").value);
  if (authProfiles) data.auth_profiles = authProfiles;
  const tokenPath = $("auth-token-path").value.trim();
  if (tokenPath) data.token_path = tokenPath;
  const headerName = $("auth-header-name").value.trim();
  if (headerName) data.header_name = headerName;
  const headerFormat = $("auth-header-format").value.trim();
  if (headerFormat) data.header_format = headerFormat;
  return data;
}

async function validateAuthAgainstOpenapi(data) {
  try {
    const args = {
      path: $("openapi-path").value.trim(),
      operation_id: $("auth-login-op").value,
      body: data.body,
    };
    await invoke("bridge_call", { command: "validate_login_request_contract", args });
    for (const [name, body] of Object.entries(data.auth_profiles || {})) {
      try {
        await invoke("bridge_call", { command: "validate_login_request_contract", args: { ...args, body } });
      } catch (error) {
        throw new Error(`認証プロファイル「${name}」: ${error}`, { cause: error });
      }
    }
    return true;
  } catch (error) {
    throw new Error(`ログイン設定とAPI定義が一致しません: ${error}`, { cause: error });
  }
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
    await validateAuthAgainstOpenapi(data);
    await invoke("write_config_file", { path: savePath, data });
    setAuthConfigStatus(`保存しました: ${savePath}`, "ok");
  } catch (e) {
    setAuthConfigStatus(`保存に失敗しました: ${e}`, "error");
  }
});

// ---------- 対象APIチェックリスト ----------

let lastOperations = [];

function setContractEditorStatus(message, state = "") {
  const status = $("contract-editor-status");
  status.textContent = message;
  status.classList.remove("error", "ok");
  if (state) status.classList.add(state);
}

function contractOption(label, value) {
  const option = document.createElement("option");
  option.textContent = label;
  option.value = value;
  return option;
}

import { addErrorDbScope, collectErrorDbScopes } from "./error-db-scopes.js";
$("contract-add-error-db-scope").addEventListener("click", () => addErrorDbScope($("contract-error-db-scopes")));
let contractRequestSchemaNode = null;
let contractResponseSchemaNode = null;
let contractPresenceRules = [];
let contractComparisonRules = [];

function refreshPresenceRules() {
  renderComparisonRules($("contract-comparison-rules"), contractComparisonRules, contractRequestSchemaNode);
  renderPresenceRules($("contract-presence-rules"), contractPresenceRules, contractRequestSchemaNode);
}

$("contract-add-presence-rule").addEventListener("click", () => {
  contractPresenceRules.push({ kind: "atLeastOne", fields: ["", ""] });
  refreshPresenceRules();
});

$("contract-add-comparison-rule").addEventListener("click", () => {
  contractComparisonRules.push({ fields: ["", ""], operator: "<=" });
  refreshPresenceRules();
});

function setContractSchemaBuilder(kind, schema) {
  const isRequest = kind === "request";
  const model = schema ? schemaToBuilderNode(schema) : null;
  if (isRequest) contractRequestSchemaNode = model;
  else contractResponseSchemaNode = model;
  if (isRequest) {
    contractPresenceRules = presenceRulesFromSchema(schema);
    contractComparisonRules = comparisonRulesFromSchema(schema);
    refreshPresenceRules();
  }

  renderSchemaBuilder(
    $(isRequest ? "contract-request-schema-builder" : "contract-response-schema-builder"),
    model,
    (updated) => {
      if (isRequest) {
        contractRequestSchemaNode = updated;
        refreshPresenceRules();
      }
      else contractResponseSchemaNode = updated;
    },
    { requestExamples: isRequest },
  );
}

function resetContractEditor() {
  $("contract-operation").replaceChildren(contractOption("OpenAPIを選択してください", ""));
  $("contract-error-db-scopes").replaceChildren();
  $("contract-operation").disabled = true;
  $("contract-load-button").disabled = true;
  $("contract-save-button").disabled = true;
  $("contract-request-required").checked = false;
  setContractSchemaBuilder("request", null);
  $("contract-response-status").value = "200";
  setContractSchemaBuilder("response", null);
  $("contract-response-empty").checked = false;
  $("contract-response-schema-builder").hidden = false;
  setContractEditorStatus("");
}

function populateContractOperationSelect() {
  const select = $("contract-operation");
  const previous = select.value;
  select.replaceChildren();
  if (lastOperations.length === 0) {
    select.appendChild(contractOption("OpenAPIを選択してください", ""));
    select.disabled = true;
    $("contract-load-button").disabled = true;
    $("contract-save-button").disabled = true;
    $("contract-request-required").checked = false;
    setContractSchemaBuilder("request", null);
    $("contract-response-status").value = "200";
    setContractSchemaBuilder("response", null);
    $("contract-response-empty").checked = false;
    $("contract-response-schema-builder").hidden = false;
    setContractEditorStatus("");
    return "";
  }

  for (const operation of lastOperations) {
    const option = contractOption(`${operation.method} ${operation.path} (${operation.operationId})`, operation.operationId);
    select.appendChild(option);
  }
  select.disabled = false;
  select.value = lastOperations.some((operation) => operation.operationId === previous)
    ? previous
    : lastOperations[0].operationId;
  $("contract-load-button").disabled = false;
  $("contract-save-button").disabled = false;
  return select.value;
}

export function contractEditorDefaultPath(sourcePath) {
  return /\.json$/i.test(sourcePath)
    ? sourcePath.replace(/\.json$/i, ".ui-edited.json")
    : `${sourcePath}.ui-edited.json`;
}

$("new-api-create").addEventListener("click", async () => {
  const button = $("new-api-create");
  const message = $("new-api-message");
  button.disabled = true;
  try {
    const sourcePath = $("new-api-append").checked ? $("openapi-path").value.trim() : "";
    if ($("new-api-append").checked && !sourcePath) throw new Error("追加先のopenapi.jsonを選択してください");
    const operationId = $("new-api-name").value.trim();
    const data = await invoke("bridge_call", {
      command: "create_operation_document",
      args: { source_path: sourcePath, route: $("new-api-path").value.trim(),
        method: $("new-api-method").value, operation_id: operationId,
        statuses: $("new-api-statuses").value.split(",").map((s) => s.trim()),
        request_body: $("new-api-body").checked },
    });
    const path = await save({ filters: [{ name: "OpenAPI JSON", extensions: ["json"] }],
      defaultPath: sourcePath ? contractEditorDefaultPath(sourcePath) : `${operationId}.openapi.json` });
    if (!path) { message.textContent = "保存をキャンセルしました"; return; }
    if (sourcePath && path.replaceAll("\\", "/").toLowerCase() === sourcePath.replaceAll("\\", "/").toLowerCase()) {
      throw new Error("元のOpenAPIとは別名で保存してください");
    }
    await invoke("write_config_file", { path, data });
    $("openapi-path").value = path;
    updateActiveOpenapiText();
    await refreshOperationsList({ keepExcluded: true });
    $("contract-operation").value = operationId;
    await loadOperationBodyContract();
    await persistSettings();
    showPage("gen", document.querySelector('[data-step="spec"]'));
    message.textContent = "APIを登録しました";
    setContractEditorStatus("新規APIの下書きです。リクエスト・レスポンスの項目を入力し、下の保存ボタンで確定してください。", "ok");
    $("contract-operation").scrollIntoView?.({ block: "start" });
  } catch (error) {
    message.textContent = `登録できませんでした: ${error.message || error}`;
  } finally {
    button.disabled = false;
  }
});

async function loadOperationBodyContract() {
  const path = $("openapi-path").value.trim();
  const operationId = $("contract-operation").value;
  if (!path || !operationId) {
    setContractEditorStatus("openapi.jsonと対象operationを選択してください", "error");
    return;
  }
  try {
    const contract = await invoke("bridge_call", {
      command: "load_operation_body_contract",
      args: { path, operation_id: operationId },
    });
    $("contract-request-required").checked = !!contract.requestBodyRequired;
    $("contract-error-db-scopes").replaceChildren();
    for (const scope of contract.errorDbUnchanged || []) addErrorDbScope($("contract-error-db-scopes"), scope);
    setContractSchemaBuilder("request", contract.requestBodySchema);
    $("contract-response-status").value = contract.responseStatus || "200";
    setContractSchemaBuilder("response", contract.responseBodySchema);
    $("contract-response-empty").checked = !!contract.responseBodyEmpty;
    $("contract-response-schema-builder").hidden = !!contract.responseBodyEmpty;
    setContractEditorStatus("選択したoperationのbody項目を読み込みました", "ok");
  } catch (error) {
    setContractEditorStatus(`OpenAPIを読み込めませんでした: ${error.message || error}`, "error");
  }
}

async function saveOperationBodyContract() {
  const sourcePath = $("openapi-path").value.trim();
  const operationId = $("contract-operation").value;
  if (!sourcePath || !operationId) {
    setContractEditorStatus("openapi.jsonと対象operationを選択してください", "error");
    return;
  }

  let requestSchema;
  let responseSchema;
  try {
    requestSchema = contractRequestSchemaNode ? builderNodeToSchema(contractRequestSchemaNode) : null;
    requestSchema = applyPresenceRules(requestSchema, contractPresenceRules);
    requestSchema = applyComparisonRules(requestSchema, contractComparisonRules);
    responseSchema = !$("contract-response-empty").checked && contractResponseSchemaNode ? builderNodeToSchema(contractResponseSchemaNode) : null;
  } catch (error) {
    setContractEditorStatus(error.message, "error");
    return;
  }

  const responseStatus = $("contract-response-status").value.trim();
  if (!/^(?:2\d\d|2XX)$/i.test(responseStatus)) {
    setContractEditorStatus("成功response statusは200〜299または2XXで指定してください", "error");
    return;
  }
  const destinationPath = await save({
    filters: [{ name: "OpenAPI JSON", extensions: ["json"] }],
    defaultPath: contractEditorDefaultPath(sourcePath),
  });
  if (!destinationPath) return;

  try {
    const result = await invoke("bridge_call", {
      command: "save_operation_body_contract",
      args: {
        source_path: sourcePath,
        destination_path: destinationPath,
        operation_id: operationId,
        request_body_required: $("contract-request-required").checked,
        request_body_schema: requestSchema,
        response_status: responseStatus,
        response_body_schema: responseSchema,
        response_body_empty: $("contract-response-empty").checked,
        error_db_unchanged: collectErrorDbScopes($("contract-error-db-scopes")),
      },
    });
    $("openapi-path").value = result.path;
    updateActiveOpenapiText();
    await refreshOperationsList({ keepExcluded: true });
    await persistSettings();
    setContractEditorStatus(
      `OpenAPIを保存し、試験対象に設定しました: ${result.path}。続けて「試験ケースを作成して確認」を押してください。`,
      "ok",
    );
  } catch (error) {
    setContractEditorStatus(`保存できませんでした: ${error.message || error}`, "error");
  }
}

$("contract-operation").addEventListener("change", loadOperationBodyContract);
$("contract-load-button").addEventListener("click", loadOperationBodyContract);
$("contract-save-button").addEventListener("click", saveOperationBodyContract);

async function refreshOperationsList({ keepExcluded, selectedOperations = null }) {
  const path = $("openapi-path").value.trim();
  const container = $("operations-list");
  if (!path) {
    container.innerHTML = '<div class="op-empty">「設定」画面でopenapi.jsonを選択すると一覧が表示されます</div>';
    lastOperations = [];
    await dbScenarioEditor.load("");
    populateAuthLoginOpSelect();
    resetContractEditor();
    return;
  }

  let ops;
  try {
    ops = await invoke("bridge_call", { command: "list_operations", args: { path } });
  } catch (e) {
    const message = document.createElement("div");
    message.className = "op-empty";
    message.textContent = `読み込みに失敗しました: ${e}`;
    container.replaceChildren(message);
    lastOperations = [];
    await dbScenarioEditor.load("");
    populateAuthLoginOpSelect();
    resetContractEditor();
    return;
  }

  lastOperations = ops || [];
  await dbScenarioEditor.load(path);
  populateAuthLoginOpSelect();
  const selectedContractOperation = populateContractOperationSelect();
  if (lastOperations.length === 0) {
    container.innerHTML = '<div class="op-empty">operationが見つかりませんでした</div>';
    return;
  }

  const excluded = selectedOperations !== null
    ? new Set(lastOperations.map((op) => op.operationId).filter((id) => !selectedOperations.includes(id)))
    : keepExcluded
      ? new Set(
        (settings.gen_excluded_operations || "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      )
      : new Set();

  container.replaceChildren();
  for (const op of lastOperations) {
    const row = document.createElement("label");
    row.className = "op-item";
    const checked = !excluded.has(op.operationId);
    const firstLine = document.createElement("span");
    firstLine.className = "op-row1";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.dataset.opId = op.operationId;
    checkbox.checked = checked;
    const method = document.createElement("span");
    method.className = "op-method";
    method.textContent = op.method;
    firstLine.append(checkbox, method);
    const path = document.createElement("span");
    path.className = "op-path";
    path.textContent = op.path;
    const operationId = document.createElement("span");
    operationId.className = "op-id";
    operationId.textContent = op.operationId;
    row.append(firstLine, path, operationId);
    container.appendChild(row);
  }

  await maybeAutofillBaseUrl(path);
  if (selectedContractOperation) await loadOperationBodyContract();
}

function projectDataFromForm() {
  const openapiPath = $("openapi-path").value.trim();
  const baseUrl = $("base-url").value.trim();
  if (!openapiPath) throw new Error("openapi.json を選択してください");
  if (!baseUrl) throw new Error("Base URL を入力してください");
  return buildProjectData({
    openapiPath,
    baseUrl,
    outputDir: $("output-dir").value.trim() || dirName(openapiPath),
    operations: lastOperations.map((operation) => operation.operationId),
    uncheckedOperations: getUncheckedOperationIds(),
    setupSqlPath: $("setup-sql-path").value.trim(),
    teardownSqlPath: $("teardown-sql-path").value.trim(),
    dbScenariosPath: $("dbscenario-path").value.trim(),
  });
}

$("project-save").addEventListener("click", async () => {
  let data;
  try {
    data = projectDataFromForm();
  } catch (e) {
    setProjectStatus(e.message, "error");
    return;
  }
  const path = await save({ filters: [{ name: "API試験プロジェクト", extensions: ["json"] }], defaultPath: "project.json" });
  if (!path) return;
  try {
    await invoke("write_config_file", { path, data });
    setProjectStatus(`保存しました: ${path}`, "ok");
  } catch {
    setProjectStatus("保存に失敗しました。保存先の書き込み権限を確認してください。", "error");
  }
});

$("project-open").addEventListener("click", async () => {
  const path = await open({ multiple: false, filters: [{ name: "API試験プロジェクト", extensions: ["json"] }] });
  if (!path) return;
  try {
    const project = await invoke("bridge_call", { command: "load_project", args: { path } });
    $("openapi-path").value = project.openapiPath;
    $("base-url").value = project.baseUrl;
    $("output-dir").value = project.outputDir;
    $("setup-sql-path").value = project.setupSqlPath || "";
    $("teardown-sql-path").value = project.teardownSqlPath || "";
    $("dbscenario-path").value = project.dbScenariosPath || "";
    updateActiveOpenapiText();
    updateActiveBaseUrlText();
    await refreshOperationsList({ keepExcluded: false, selectedOperations: project.selectedOperations || [] });
    await persistSettings();
    setProjectStatus(`開きました: ${path}`, "ok");
  } catch {
    setProjectStatus("プロジェクトを開けませんでした。project.jsonの内容を確認してください。", "error");
  }
});

async function maybeAutofillBaseUrl(path) {
  if ($("base-url").value.trim()) return;
  try {
    const url = await invoke("bridge_call", { command: "servers_url", args: { path } });
    if (url) $("base-url").value = url;
  } catch {
    // 自動入力は失敗しても致命的ではないので無視する
  }
}

export function getUncheckedOperationIds() {
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

export function joinPath(dir, name) {
  if (!dir) return name;
  return /[\\/]$/.test(dir) ? `${dir}${name}` : `${dir}\\${name}`;
}

export function buildMappingArgs(openapiPath, configPath, outputPath, schema, phpEvidencePath = "") {
  const args = [openapiPath, "--config", configPath, "-o", outputPath];
  if (schema?.trim()) args.push("--schema", schema.trim());
  if (phpEvidencePath?.trim()) args.push("--php-db-evidence", phpEvidencePath.trim());
  return args;
}

export function dirName(path) {
  const idx = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return idx >= 0 ? path.slice(0, idx) : "";
}

// ---------- 1本のスクリプトを実行してログ欄に流し込む（DB準備用） ----------
// テスト生成・実行/DBシナリオの「2段階・キャンセル可能」な実行とは別に、単発で終わる
// SQL生成スクリプトを実行する軽量な仕組み。同じ
// run_script/proc-line/proc-doneイベントを共有するため、下のリスナーでrunIdを見て振り分ける。

const simpleRuns = new Map();

export function runSimpleScript(script, args, { logEl, statusEl, doneMessage } = {}) {
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
    invoke("run_script", { runId, script, args }).catch((e) => {
      if (!simpleRuns.has(runId)) return;
      simpleRuns.delete(runId);
      if (statusEl) {
        statusEl.textContent = `スクリプトの起動に失敗しました: ${e}`;
        statusEl.classList.add("error");
      }
      resolve(-1);
    });
  });
}

// ---------- DB準備（setup.sql/teardown.sqlの生成） ----------

function showDbPrepError(message) {
  const el = $("dbprep-error");
  el.textContent = message;
  el.hidden = false;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideDbPrepError() {
  $("dbprep-error").hidden = true;
}

$("dbprep-goto-settings").addEventListener("click", () => showPage("settings"));
$("dbprep-goto-dbscenario").addEventListener("click", () => showPage("db-scenario"));
$("dbprep-browse-sql-output-dir").addEventListener("click", () => browseDir("dbprep-sql-output-dir"));

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

// ---------- DBシナリオ（生成したシナリオYAMLの実行） ----------

let dbScenarioResultPath = null;
let dbScenarioFailedCaseIds = [];
let pendingDbScenarioCaseIds = [];
let currentDbScenarioCaseMaster = null;
let currentDbScenarioCaseMasterPath = null;
let dbScenarioPreparedRunId = null;
let dbScenarioPreparedProjectData = null;
let dbScenarioPreparationCompleted = false;
let dbScenarioPreparingCases = false;
let dbScenarioTempDbConfigPath = null;
let dbScenarioTempAuthConfigPath = null;
let dbScenarioTempProjectPath = null;

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
  $("dbscenario-next-action").textContent = "";
  const el = $("dbscenario-status");
  el.textContent = text;
  el.dataset.state = state || "";
}

function appendDbScenarioLog(line) {
  const log = $("dbscenario-log");
  log.textContent += (log.textContent ? "\n" : "") + line;
  log.scrollTop = log.scrollHeight;
}

const ARTIFACT_LABELS = {
  cases_json: "テストケースJSON",
  case_master_json: "試験ケースマスター（下書き）",
  spec_excel: "試験仕様Excel",
  result_excel: "試験結果Excel",
  junit_xml: "JUnit XML",
  db_report_excel: "DB試験結果Excel",
  db_junit_xml: "DB JUnit XML",
  db_evidence_json: "DB比較エビデンスJSON",
  contract_db_evidence_json: "異常系DB変更なしエビデンスJSON",
  html_report: "HTML結果レポート",
  failed_case_ids_json: "失敗ケースID一覧",
};

export function artifactLabel(kind) {
  return ARTIFACT_LABELS[kind] || kind;
}

export function appendArtifact(containerId, event) {
  const container = $(containerId);
  const item = document.createElement("div");
  item.className = "artifact-item";
  item.dataset.artifactKind = event.kind;
  const primary = ["html_report", "result_excel", "db_report_excel"].includes(event.kind);
  item.classList.toggle("artifact-primary", primary);
  const name = document.createElement("span");
  name.className = "artifact-item-name";
  name.textContent = artifactLabel(event.kind);
  const path = document.createElement("span");
  path.className = "artifact-item-path";
  path.textContent = event.path;
  path.title = event.path;
  const openButton = document.createElement("button");
  openButton.className = "secondary";
  openButton.textContent = event.kind === "html_report" ? "結果を確認" : "開く";
  const message = document.createElement("span");
  message.className = "artifact-message";
  message.setAttribute("role", "status");
  message.textContent = ({html_report: "合否を一覧し、要確認の試験やAPI名で絞り込めます。",
    result_excel: "最初の「結果サマリー」で期待値と実測値を比較できます。",
    db_report_excel: "「結果サマリー」から判定理由・DB比較の詳細を確認できます。"})[event.kind] || "";
  openButton.addEventListener("click", async () => {
    await openPath(event.path).catch(() => { message.textContent = "ファイルを開けませんでした。保存場所を確認してください。"; });
  });
  const location = document.createElement("details");
  const label = document.createElement("summary"); label.textContent = "保存場所";
  location.append(label, path);
  item.append(name, openButton, message, location);
  if (event.kind === "html_report") container.prepend(item);
  else if (primary) container.insertBefore(item, container.querySelector('.artifact-item:not(.artifact-primary)'));
  else container.appendChild(item);
}

const REVIEW_LABELS = { draft: "下書き・未確認", reviewed: "レビュー済み", approved: "承認済み" };
const REVIEW_NEXT = {
  draft: ["reviewed", "レビュー済みにする"],
  reviewed: ["approved", "承認する"],
  approved: ["reviewed", "承認を戻す"],
};
let caseReviewSaving = false;

function syncPreparedExecutionButtons() {
  const contractCases = currentCaseMaster?.cases?.filter((item) => item.kind === "contract") || [];
  const ready = preparationCompleted && preparedCaseRunId && contractCases.length > 0;
  const allApproved = ready && contractCases.every((item) => item.reviewStatus === "approved");
  $("run-button").hidden = Boolean(ready);
  $("execute-approved-button").hidden = !allApproved;
  $("execute-draft-button").hidden = !ready;
  $("execute-approved-button").disabled = workflowClient.isRunning();
  $("execute-draft-button").disabled = workflowClient.isRunning();
}

function syncDbPreparedExecutionButtons() {
  const cases = currentDbScenarioCaseMaster?.cases || [];
  const ready = dbScenarioPreparationCompleted && dbScenarioPreparedRunId && cases.length > 0;
  const allApproved = ready && cases.every((item) => item.reviewStatus === "approved");
  $("dbscenario-run-button").hidden = Boolean(ready);
  $("dbscenario-execute-approved-button").hidden = !allApproved;
  $("dbscenario-execute-draft-button").hidden = !ready;
  $("dbscenario-execute-approved-button").disabled = workflowClient.isRunning();
  $("dbscenario-execute-draft-button").disabled = workflowClient.isRunning();
}

function renderCaseMasterView(master, masterPath, ids, rerender) {
  const panel = $(ids.panel);
  const list = $(ids.list);
  const cases = Array.isArray(master?.cases) ? master.cases : [];
  panel.hidden = cases.length === 0 && !master?.coverage?.length;
  list.replaceChildren();
  const counts = { draft: 0, reviewed: 0, approved: 0 };
  for (const testCase of cases) counts[testCase.reviewStatus] = (counts[testCase.reviewStatus] || 0) + 1;
  $(ids.summary).textContent = `${cases.length}件: 未確認 ${counts.draft} / レビュー済み ${counts.reviewed} / 承認済み ${counts.approved}`;

  if (Array.isArray(master?.coverage) && master.coverage.length) {
    const coverage = document.createElement("details");
    coverage.className = "coverage-review";
    const heading = document.createElement("summary");
    const gaps = master.coverage.filter((row) => ["未生成", "未対応", "一部対応", "未照合", "ケース未設定", "要手動確認"].includes(row.status));
    heading.textContent = `仕様の対応状況：要確認 ${gaps.length}件 / ${master.coverage.length}項目（試験の合否とは別）`;
    coverage.open = gaps.length > 0;
    const table = document.createElement("table");
    const header = document.createElement("tr");
    for (const label of ["API操作", "場所・項目", "制約", "状態", "試験ID・補足"]) {
      const th = document.createElement("th"); th.textContent = label; header.append(th);
    }
    table.append(header);
    for (const row of master.coverage) {
      const tr = document.createElement("tr");
      for (const text of [row.operationId, `${row.location} / ${row.field}`, row.keyword, row.status,
        `${(row.caseIds || []).join(", ")} ${row.detail || ""}`]) {
        const td = document.createElement("td"); td.textContent = text; tr.append(td);
      }
      table.append(tr);
    }
    const filterLabel = document.createElement("label");
    const filter = document.createElement("input");
    filter.type = "checkbox";
    filter.checked = gaps.length > 0;
    filterLabel.append(filter, " 要確認の項目だけ表示");
    const applyFilter = () => {
      Array.from(table.rows).slice(1).forEach((tr, index) => {
        tr.hidden = filter.checked && !gaps.includes(master.coverage[index]);
      });
    };
    filter.addEventListener("change", applyFilter);
    applyFilter();
    coverage.append(heading, filterLabel, table); list.append(coverage);
  }

  for (const testCase of cases) {
    const card = document.createElement("article");
    card.className = "case-review-card";
    card.dataset.caseId = testCase.caseId;
    const heading = document.createElement("div");
    heading.className = "case-review-card-heading";
    const title = document.createElement("strong");
    title.textContent = `${testCase.caseId} - ${testCase.title || "（名称なし）"}`;
    const status = document.createElement("span");
    status.className = "case-review-status";
    status.textContent = REVIEW_LABELS[testCase.reviewStatus] || REVIEW_LABELS.draft;
    heading.append(title, status);
    const source = document.createElement("p");
    source.className = "case-review-source";
    source.textContent = `${testCase.kind === "db-scenario" ? "Layer 2（DB）" : "Layer 1"} / ${testCase.source?.operationId || ""} / ${testCase.source?.path || ""}`;
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "入力・期待結果を確認";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify({ definition: testCase.definition, expected: testCase.expected }, null, 2);
    details.append(summary, pre);
    const action = document.createElement("button");
    action.className = "secondary";
    const [nextStatus, actionLabel] = REVIEW_NEXT[testCase.reviewStatus] || REVIEW_NEXT.draft;
    action.textContent = actionLabel;
    action.disabled = workflowClient.isRunning();
    action.addEventListener("click", async () => {
      if (!masterPath || workflowClient.isRunning() || caseReviewSaving) return;
      caseReviewSaving = true;
      list.querySelectorAll('button').forEach((button) => { button.disabled = true; });
      try {
        const updated = await invoke("bridge_call", {
          command: "save_case_master_reviews",
          args: { path: masterPath, updates: { [testCase.caseId]: nextStatus } },
        });
        caseReviewSaving = false;
        rerender(updated, masterPath);
        $(ids.message).textContent = `${testCase.caseId} を「${REVIEW_LABELS[nextStatus]}」にしました。`;
      } catch {
        caseReviewSaving = false;
        list.querySelectorAll('button').forEach((button) => { button.disabled = workflowClient.isRunning(); });
        $(ids.message).textContent = "レビュー状態を保存できませんでした。試験ケースマスターのファイル権限を確認してください。";
      }
    });
    card.append(heading, source, details, action);
    list.appendChild(card);
  }
  return master;
}

export function renderCaseMaster(master, masterPath) {
  currentCaseMaster = renderCaseMasterView(master, masterPath, {
    panel: "case-review-panel", list: "case-review-list", summary: "case-review-summary", message: "case-review-message",
  }, renderCaseMaster);
  currentCaseMasterPath = masterPath;
  syncPreparedExecutionButtons();
  return currentCaseMaster;
}

export function renderDbScenarioCaseMaster(master, masterPath) {
  currentDbScenarioCaseMaster = renderCaseMasterView(master, masterPath, {
    panel: "dbscenario-case-review-panel", list: "dbscenario-case-review-list",
    summary: "dbscenario-case-review-summary", message: "dbscenario-case-review-message",
  }, renderDbScenarioCaseMaster);
  currentDbScenarioCaseMasterPath = masterPath;
  syncDbPreparedExecutionButtons();
  return currentDbScenarioCaseMaster;
}

function handleDbScenarioWorkflowEvent(event) {
  if (event.type === "artifact" && event.path) {
    if (event.kind === "db_report_excel") dbScenarioResultPath = event.path;
    appendArtifact("dbscenario-artifacts", event);
    appendDbScenarioLog(`[INFO] 成果物を出力しました: ${event.path}`);
    if (event.kind === "case_master_json") {
      currentDbScenarioCaseMasterPath = event.path;
      if (dbScenarioPreparingCases) {
        dbScenarioPreparedRunId = event.path.split(/[\\/]/).at(-2) || null;
      }
      invoke("bridge_call", { command: "load_case_master", args: { path: event.path } })
        .then((master) => {
          renderDbScenarioCaseMaster(master, event.path);
          if (dbScenarioPreparationCompleted) syncDbPreparedExecutionButtons();
        })
        .catch(() => {
          $("dbscenario-case-review-message").textContent = "試験ケースマスターを読み込めませんでした。ファイルを確認してください。";
        });
    }
    if (event.kind === "failed_case_ids_json") {
      invoke("bridge_call", { command: "load_failed_case_ids", args: { path: event.path } })
        .then((ids) => {
          dbScenarioFailedCaseIds = ids;
          $("dbscenario-rerun-failed-button").hidden = ids.length === 0;
          $("dbscenario-rerun-failed-button").disabled = ids.length === 0 || workflowClient.isRunning();
        })
        .catch(() => appendDbScenarioLog("[WARN] 失敗ケース一覧を読み込めませんでした"));
    }
    return;
  }
  if (event.type === "log" || event.type === "progress" || event.type === "stage_started") {
    if (event.message) appendDbScenarioLog(event.message);
    return;
  }
  if (event.type === "stage_finished" && event.status === "error" && event.message) {
    appendDbScenarioLog(`[ERROR] ${event.message}`);
  }
}

function finishDbScenarioRunUi(code) {
  const meaning = { 0: "OK：すべてのDB確認に成功", 1: "NG：失敗したDB確認があります", 2: "WARNING：警告があります", 3: "ERROR：実行エラー", 130: "キャンセルしました" }[code] || `終了コード ${code}`;
  const state = { 0: "ok", 1: "ng", 2: "warn", 130: "warn" }[code] || "ng";
  setDbScenarioStatus(meaning, state);
  $("dbscenario-next-action").textContent = runOutcomeAdvice(code);
  $("dbscenario-run-button").disabled = false;
  $("dbscenario-cancel-button").disabled = true;
  if (dbScenarioFailedCaseIds.length) $("dbscenario-rerun-failed-button").disabled = false;
  if (dbScenarioResultPath) {
    $("dbscenario-open-result-button").disabled = false;
  }
}

function finishDbScenarioPrepareUi(code) {
  const meaning = code === 0
    ? { text: "実行前の確認を準備しました。内容を確認して実行してください", state: "ok" }
    : { text: `ケース準備に失敗しました（終了コード ${code}）`, state: "error" };
  setDbScenarioStatus(meaning.text, meaning.state);
  $("dbscenario-run-button").disabled = false;
  $("dbscenario-cancel-button").disabled = true;
  if (code === 0) {
    dbScenarioPreparationCompleted = true;
    invalidateChangedPreparation();
    if (currentDbScenarioCaseMaster) {
      renderDbScenarioCaseMaster(currentDbScenarioCaseMaster, currentDbScenarioCaseMasterPath);
    }
  } else {
    dbScenarioPreparationCompleted = false;
    dbScenarioPreparedRunId = null;
    dbScenarioPreparedProjectData = null;
  }
  syncDbPreparedExecutionButtons();
}

// DB接続設定/認証設定の一時ファイル（パスワード等を含む）は、proc-done の到達有無に
// 関わらず必ず片付ける。run_script の起動そのものが失敗した場合もこの関数経由で
// 片付けるため、呼び出し漏れによる平文認証情報の残存を防ぐ。
function cleanupDbScenarioTempConfigFiles() {
  if (dbScenarioTempDbConfigPath) {
    invoke("delete_file", { path: dbScenarioTempDbConfigPath }).catch(() => {});
    dbScenarioTempDbConfigPath = null;
  }
  if (dbScenarioTempAuthConfigPath) {
    invoke("delete_file", { path: dbScenarioTempAuthConfigPath }).catch(() => {});
    dbScenarioTempAuthConfigPath = null;
  }
  if (dbScenarioTempProjectPath) {
    invoke("delete_file", { path: dbScenarioTempProjectPath }).catch(() => {});
    dbScenarioTempProjectPath = null;
  }
}

$("dbscenario-goto-settings").addEventListener("click", () => showPage("settings"));
$("dbscenario-browse").addEventListener("click", () =>
  browseFile("dbscenario-path", [{ name: "YAML", extensions: ["yaml", "yml"] }]),
);

async function writeDbScenarioRuntimeConfigs() {
  if (!dbConfigEnabled()) throw new Error("DB接続設定（「設定」画面）が必要です");
  const dbConfigData = collectDbConfig();
  const configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
  dbScenarioTempDbConfigPath = configPath;

  let authConfigPath = "";
  if (authConfigEnabled()) {
    const authConfigData = collectAuthConfig();
    await validateAuthAgainstOpenapi(authConfigData);
    authConfigPath = await invoke("write_config_file", { path: null, data: authConfigData });
    dbScenarioTempAuthConfigPath = authConfigPath;
  }
  return { configPath, authConfigPath };
}

async function executePreparedDbScenarios(allowDraft) {
  invalidateChangedPreparation();
  const cases = currentDbScenarioCaseMaster?.cases || [];
  if (!dbScenarioPreparationCompleted || !dbScenarioPreparedRunId || !dbScenarioPreparedProjectData || !cases.length) {
    showDbScenarioError("実行前の確認内容がありません。先に準備してください");
    return;
  }
  const unapproved = cases.filter((item) => item.reviewStatus !== "approved");
  if (!allowDraft && unapproved.length) {
    showDbScenarioError("未確認の試験があります。内容を確認してから実行してください");
    return;
  }

  try {
    const { configPath, authConfigPath } = await writeDbScenarioRuntimeConfigs();
    dbScenarioTempProjectPath = await invoke("write_config_file", {
      path: null, data: dbScenarioPreparedProjectData,
    });
    invalidateChangedPreparation();
    if (!dbScenarioPreparationCompleted) throw new Error("設定が変更されたため実行を中止しました。再準備してください。");
    const caseRunId = dbScenarioPreparedRunId;
    dbScenarioResultPath = null;
    dbScenarioFailedCaseIds = [];
    $("dbscenario-rerun-failed-button").hidden = true;
    $("dbscenario-log").textContent = "";
    $("dbscenario-artifacts").replaceChildren();
    $("dbscenario-run-button").disabled = true;
    $("dbscenario-cancel-button").disabled = false;
    $("dbscenario-open-result-button").disabled = true;
    setDbScenarioStatus("実行中...", "running");
    const completion = workflowClient.executeDb({
      projectPath: dbScenarioTempProjectPath,
      preparedRunId: caseRunId,
      runtimeConfigPath: configPath,
      authConfigPath: authConfigPath || undefined,
      persistCookies: $("dbscenario-cookie-jar").checked,
      dryRun: $("dbscenario-dry-run").checked,
      allowDraft,
    }, { onEvent: handleDbScenarioWorkflowEvent });
    renderDbScenarioCaseMaster(currentDbScenarioCaseMaster, currentDbScenarioCaseMasterPath);
    const { code } = await completion;
    dbScenarioPreparationCompleted = false;
    dbScenarioPreparedRunId = null;
    dbScenarioPreparedProjectData = null;
    finishDbScenarioRunUi(code);
    syncDbPreparedExecutionButtons();
  } catch (e) {
    appendDbScenarioLog(`[ERROR] ${e.message || "処理を開始できませんでした"}`);
    dbScenarioPreparationCompleted = false;
    dbScenarioPreparedRunId = null;
    dbScenarioPreparedProjectData = null;
    finishDbScenarioRunUi(3);
    syncDbPreparedExecutionButtons();
  } finally {
    cleanupDbScenarioTempConfigFiles();
  }
}

$("dbscenario-execute-approved-button").addEventListener("click", () => executePreparedDbScenarios(false));
$("dbscenario-execute-draft-button").addEventListener("click", () => executePreparedDbScenarios(true));

$("dbscenario-run-button").addEventListener("click", async () => {
  const preparationSnapshot = preparationSettings();
  hideDbScenarioError();

  if (workflowClient.isRunning()) {
    showDbScenarioError("別の試験を実行中です。完了またはキャンセルしてから開始してください");
    return;
  }

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
    showDbScenarioError("DB確認設定ファイルを選択してください。上の対応設定を保存するか、既存のYAMLを選んでください");
    return;
  }

  const outputDir = $("output-dir").value.trim() || dirName(openapiPath);
  const projectData = buildProjectData({
    openapiPath,
    baseUrl,
    outputDir,
    operations: lastOperations.map((operation) => operation.operationId),
    uncheckedOperations: getUncheckedOperationIds(),
    dbScenariosPath: scenarioPath,
  });

  try {
    await persistSettings();
    const caseIds = pendingDbScenarioCaseIds;
    pendingDbScenarioCaseIds = [];
    if (!caseIds.length) {
      dbScenarioTempProjectPath = await invoke("write_config_file", { path: null, data: projectData });
      dbScenarioResultPath = null;
      currentDbScenarioCaseMaster = null;
      currentDbScenarioCaseMasterPath = null;
      dbScenarioFailedCaseIds = [];
      dbScenarioPreparedProjectData = projectData;
      dbPreparationSettings = preparationSnapshot;
      dbScenarioPreparedRunId = null;
      dbScenarioPreparationCompleted = false;
      dbScenarioPreparingCases = true;
      syncDbPreparedExecutionButtons();
      $("dbscenario-rerun-failed-button").hidden = true;
      $("dbscenario-log").textContent = "";
      $("dbscenario-artifacts").replaceChildren();
      $("dbscenario-run-button").disabled = true;
      $("dbscenario-cancel-button").disabled = false;
      $("dbscenario-open-result-button").disabled = true;
      setDbScenarioStatus("実行前の確認内容を準備中...", "running");
      try {
        const { code } = await workflowClient.prepareDb({
          projectPath: dbScenarioTempProjectPath,
        }, { onEvent: handleDbScenarioWorkflowEvent });
        finishDbScenarioPrepareUi(code);
      } catch (e) {
        appendDbScenarioLog(`[ERROR] ${e.message || "ケース準備を開始できませんでした"}`);
        finishDbScenarioPrepareUi(3);
      } finally {
        dbScenarioPreparingCases = false;
        cleanupDbScenarioTempConfigFiles();
      }
      return;
    }

    const { configPath, authConfigPath } = await writeDbScenarioRuntimeConfigs();
    dbScenarioTempProjectPath = await invoke("write_config_file", { path: null, data: projectData });
    dbScenarioResultPath = null;
    dbScenarioFailedCaseIds = [];
    dbScenarioPreparedRunId = null;
    dbScenarioPreparedProjectData = null;
    dbScenarioPreparationCompleted = false;
    $("dbscenario-rerun-failed-button").hidden = true;
    $("dbscenario-log").textContent = "";
    $("dbscenario-artifacts").replaceChildren();
    $("dbscenario-run-button").disabled = true;
    $("dbscenario-cancel-button").disabled = false;
    $("dbscenario-open-result-button").disabled = true;
    setDbScenarioStatus("実行中...", "running");
    const { code } = await workflowClient.run({
      workflow: "db-scenarios",
      projectPath: dbScenarioTempProjectPath,
      runtimeConfigPath: configPath,
      authConfigPath: authConfigPath || undefined,
      persistCookies: $("dbscenario-cookie-jar").checked,
      dryRun: $("dbscenario-dry-run").checked,
      caseIds,
    }, { onEvent: handleDbScenarioWorkflowEvent });
    finishDbScenarioRunUi(code);
  } catch (e) {
    appendDbScenarioLog(`[ERROR] ${e.message || "処理を開始できませんでした"}`);
    finishDbScenarioRunUi(3);
  } finally {
    cleanupDbScenarioTempConfigFiles();
  }
});

$("dbscenario-rerun-failed-button").addEventListener("click", () => {
  if (!dbScenarioFailedCaseIds.length) return;
  pendingDbScenarioCaseIds = [...dbScenarioFailedCaseIds];
  $("dbscenario-run-button").click();
});

$("dbscenario-cancel-button").addEventListener("click", async () => {
  await workflowClient.cancel();
});

$("dbscenario-open-result-button").addEventListener("click", async () => {
  if (dbScenarioResultPath) {
    await openPath(dbScenarioResultPath).catch(() => {});
  }
});

// ---------- 実行（生成→実行の2段階） ----------

let currentResultPath = null;
let currentCaseMasterPath = null;
let currentCaseMaster = null;
let currentFailedCaseIds = [];
let pendingCaseIds = [];
let preparedCaseRunId = null;
let preparedProjectData = null;
let preparationCompleted = false;
let preparingCases = false;
let tempDbConfigPath = null;
let tempAuthConfigPath = null;
let tempProjectPath = null;
let progressTotal = 0;
let progressDone = 0;

// DB接続設定/認証設定の一時ファイル（パスワード等を含む）は、生成→実行の2段階の
// どちらで終わっても必ず片付ける。呼び出し漏れがあると平文の認証情報が
// 一時フォルダに残り続けるため、終了パス（成功/失敗/キャンセル）ごとに個別実装せず
// 必ずこの関数経由で片付ける。
async function cleanupGenTempConfigFiles() {
  const paths = [tempDbConfigPath, tempAuthConfigPath, tempProjectPath].filter(Boolean);
  tempDbConfigPath = null;
  tempAuthConfigPath = null;
  tempProjectPath = null;
  await Promise.all(paths.map((path) => invoke("delete_file", { path }).catch(() => {})));
}

function appendLog(line) {
  const log = $("run-log");
  log.textContent += (log.textContent ? "\n" : "") + line;
  log.scrollTop = log.scrollHeight;
  feedProgress(line);
}

export function feedProgress(line) {
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
  $("run-next-action").textContent = "";
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
  $("run-artifacts").replaceChildren();
  progressTotal = 0;
  progressDone = 0;
  updateProgressBar();
  $("run-button").disabled = true;
  $("run-schemathesis-button").disabled = true;
  $("execute-approved-button").disabled = true;
  $("execute-draft-button").disabled = true;
  $("cancel-button").disabled = false;
  $("open-result-button").disabled = true;
  $("rerun-failed-button").hidden = true;
  currentFailedCaseIds = [];
  setStatus("実行中...", "running");
}

function finishPrepareUi(code) {
  const meaning = code === 0
    ? { text: "ケース準備完了：内容を確認し、承認または予備実行を選んでください", state: "ok" }
    : code === 130
      ? { text: "ケース準備をキャンセルしました", state: "warn" }
      : { text: `ケース準備に失敗しました（終了コード ${code}）。ログを確認してください`, state: "error" };
  setStatus(meaning.text, meaning.state);
  $("run-button").disabled = false;
  $("run-schemathesis-button").disabled = false;
  $("cancel-button").disabled = true;
  $("open-result-button").disabled = true;
  if (code === 0) {
    preparationCompleted = true;
    invalidateChangedPreparation();
    if (currentCaseMaster) renderCaseMaster(currentCaseMaster, currentCaseMasterPath);
    syncPreparedExecutionButtons();
  } else {
    preparationCompleted = false;
    preparedCaseRunId = null;
    preparedProjectData = null;
    syncPreparedExecutionButtons();
  }
}

const RUN_STAGE_MEANING = {
  0: "OK：全ケース成功",
  1: "NG：1件以上失敗",
  2: "WARNING：警告・未確認があります（応答時間超過など）",
  3: "ERROR：実行エラー",
  4: "ERROR：設定エラー",
  130: "キャンセルしました",
};
const RUN_STATE_BY_CODE = { 0: "ok", 1: "ng", 2: "warn", 130: "warn" };

export function runStatusMeaning(code) {
  return { text: RUN_STAGE_MEANING[code] || `終了コード ${code}`, state: RUN_STATE_BY_CODE[code] || "ng" };
}

export function runOutcomeAdvice(code) {
  if (code === 0) return "実行したケースが成功しました。未実行ケースと「仕様の対応状況」の要確認項目は別に確認してください。";
  if (code === 1) return "結果サマリーのNGから、期待値・実際の値・不一致理由を確認してください。401/403の場合は認証設定と権限を確認してください。";
  if (code === 2) return "警告・未確認は合格ではありません。結果サマリーの理由と未照合項目を確認してください。";
  if (code === 4) return "API定義、Base URL、DB接続先、保存済みの対応設定を確認してください。詳しい不足箇所は実行ログに表示します。";
  if (code === 130) return "送信済みのAPIがDBを変更している場合があります。実行ログとDBの状態を確認してから再実行してください。キャンセルはロールバックを保証しません。";
  return "実行ログのエラーを確認してください。接続エラーならBase URL・DB接続先・VPN、認証エラーなら認証情報を確認してください。変更系APIの再実行前にはDBの状態も確認してください。";
}

function finishRunUi(code) {
  const { text, state } = runStatusMeaning(code);
  setStatus(text, state);
  $("run-next-action").textContent = runOutcomeAdvice(code);
  $("run-button").disabled = false;
  $("run-schemathesis-button").disabled = false;
  $("cancel-button").disabled = true;
  if (currentCaseMaster) renderCaseMaster(currentCaseMaster, currentCaseMasterPath);
  if (currentResultPath) {
    $("run-progress-bar").style.width = "100%";
    $("open-result-button").disabled = false;
  }
  $("rerun-failed-button").disabled = currentFailedCaseIds.length === 0;
}

function handleContractWorkflowEvent(event) {
  if (event.type === "artifact" && event.path) {
    if (event.kind === "result_excel") currentResultPath = event.path;
    appendArtifact("run-artifacts", event);
    appendLog(`[INFO] 成果物を出力しました: ${event.path}`);
    if (event.kind === "case_master_json") {
      currentCaseMasterPath = event.path;
      if (preparingCases) {
        preparedCaseRunId = event.path.split(/[\\/]/).at(-2) || null;
      }
      invoke("bridge_call", { command: "load_case_master", args: { path: event.path } })
        .then((master) => {
          renderCaseMaster(master, event.path);
          if (preparationCompleted) syncPreparedExecutionButtons();
        })
        .catch(() => {
          $("case-review-message").textContent = "試験ケースマスターを読み込めませんでした。ファイルを確認してください。";
        });
    }
    if (event.kind === "failed_case_ids_json") {
      invoke("bridge_call", { command: "load_failed_case_ids", args: { path: event.path } })
        .then((ids) => {
          currentFailedCaseIds = ids;
          $("rerun-failed-button").hidden = ids.length === 0;
          $("rerun-failed-button").disabled = ids.length === 0 || workflowClient.isRunning();
        })
        .catch(() => appendLog("[WARN] 失敗ケース一覧を読み込めませんでした"));
    }
    return;
  }
  if (event.type === "log" || event.type === "progress" || event.type === "stage_started") {
    if (event.message) appendLog(event.message);
    return;
  }
  if (event.type === "stage_finished" && event.status === "error" && event.message) {
    appendLog(`[ERROR] ${event.message}`);
  }
}

async function runSchemathesisExploration() {
  hideGenError();
  if (workflowClient.isRunning()) {
    showGenError("別の試験を実行中です。完了またはキャンセルしてから開始してください");
    return;
  }

  let projectData;
  try {
    projectData = projectDataFromForm();
  } catch (error) {
    showGenError(error.message);
    return;
  }
  if (!lastOperations.length || !projectData.selectedOperations.length) {
    showGenError("対象APIを少なくとも1つ選択してください（サイドバーの「対象API」）");
    return;
  }

  const maxExamplesText = $("schemathesis-max-examples").value.trim();
  const maxExamples = Number(maxExamplesText);
  if (!/^\d+$/.test(maxExamplesText) || !Number.isSafeInteger(maxExamples) || maxExamples < 1 || maxExamples > 100) {
    showGenError("API操作ごとの生成数は1から100の整数で入力してください");
    return;
  }

  const includeMutating = $("schemathesis-include-mutating").checked;
  if (includeMutating && !window.confirm(
    "POST/PUT/PATCH/DELETEを含む試験を実行します。開発DBのデータを変更したり、試験後も残す可能性があります。\n\n破棄できる開発環境を対象にしていることを確認しましたか？",
  )) return;

  try {
    await invoke("ensure_output_dir", { path: projectData.outputDir });
    await persistSettings();
    let authConfigPath = "";
    if (authConfigEnabled()) {
      const authConfigData = collectAuthConfig();
      await validateAuthAgainstOpenapi(authConfigData);
      authConfigPath = await invoke("write_config_file", { path: null, data: authConfigData });
      tempAuthConfigPath = authConfigPath;
    }
    tempProjectPath = await invoke("write_config_file", { path: null, data: projectData });
    currentResultPath = null;
    startRunUi();
    const { code } = await workflowClient.runSchemathesis({
      projectPath: tempProjectPath,
      authConfigPath: authConfigPath || undefined,
      includeMutating,
      maxExamples,
      saveCassette: $("schemathesis-save-cassette").checked,
    }, { onEvent: handleContractWorkflowEvent });
    finishRunUi(code);
  } catch (error) {
    appendLog(`[ERROR] ${error.message || "探索的試験を開始できませんでした"}`);
    finishRunUi(3);
  } finally {
    await cleanupGenTempConfigFiles();
  }
}

$("run-schemathesis-button").addEventListener("click", runSchemathesisExploration);

async function writeContractRuntimeConfigs() {
  let configPath = "";
  if (dbConfigEnabled()) {
    const dbConfigData = collectDbConfig();
    configPath = await invoke("write_config_file", { path: null, data: dbConfigData });
    tempDbConfigPath = configPath;
  }

  let authConfigPath = "";
  if (authConfigEnabled()) {
    const authConfigData = collectAuthConfig();
    await validateAuthAgainstOpenapi(authConfigData);
    authConfigPath = await invoke("write_config_file", { path: null, data: authConfigData });
    tempAuthConfigPath = authConfigPath;
  }
  return { configPath, authConfigPath };
}

async function executePreparedContract(allowDraft) {
  invalidateChangedPreparation();
  const contractCases = currentCaseMaster?.cases?.filter((item) => item.kind === "contract") || [];
  if (!preparationCompleted || !preparedCaseRunId || !preparedProjectData || !contractCases.length) {
    showGenError("試験ケースが準備されていません。先にケースを作成してください");
    return;
  }
  const unapproved = contractCases.filter((item) => item.reviewStatus !== "approved");
  if (!allowDraft && unapproved.length) {
    showGenError("承認されていないケースがあります。内容を確認して承認するか、予備実行を選んでください");
    return;
  }
  const parallelText = $("parallel").value.trim();
  const parallel = parallelText ? Number(parallelText) : 1;
  if (!Number.isSafeInteger(parallel) || parallel < 1) {
    showGenError("同時実行数は1以上の整数で入力してください");
    return;
  }
  if ($("cookie-jar").checked && parallel > 1) {
    showGenError("cookie-jar と 同時実行数(2以上) は同時に指定できません");
    return;
  }

  try {
    const { configPath, authConfigPath } = await writeContractRuntimeConfigs();
    tempProjectPath = await invoke("write_config_file", { path: null, data: preparedProjectData });
    invalidateChangedPreparation();
    if (!preparationCompleted) throw new Error("設定が変更されたため実行を中止しました。再準備してください。");
    const caseRunId = preparedCaseRunId;
    startRunUi();
    const { code } = await workflowClient.execute({
      projectPath: tempProjectPath,
      preparedRunId: caseRunId,
      runtimeConfigPath: configPath || undefined,
      authConfigPath: authConfigPath || undefined,
      parallel,
      failFast: $("fail-fast").checked,
      persistCookies: $("cookie-jar").checked,
      dryRun: $("dry-run").checked,
      fullBody: $("full-body").checked,
      allowDraft,
    }, { onEvent: handleContractWorkflowEvent });
    preparationCompleted = false;
    preparedCaseRunId = null;
    preparedProjectData = null;
    finishRunUi(code);
    syncPreparedExecutionButtons();
  } catch (e) {
    appendLog(`[ERROR] ${e.message || "処理を開始できませんでした"}`);
    preparationCompleted = false;
    preparedCaseRunId = null;
    preparedProjectData = null;
    finishRunUi(3);
    syncPreparedExecutionButtons();
  } finally {
    await cleanupGenTempConfigFiles();
  }
}

$("execute-approved-button").addEventListener("click", () => executePreparedContract(false));
$("execute-draft-button").addEventListener("click", () => executePreparedContract(true));

$("rerun-failed-button").addEventListener("click", () => {
  if (!currentFailedCaseIds.length) return;
  pendingCaseIds = [...currentFailedCaseIds];
  $("run-button").click();
});

$("run-button").addEventListener("click", async () => {
  const preparationSnapshot = preparationSettings();
  hideGenError();

  if (workflowClient.isRunning()) {
    showGenError("別の試験を実行中です。完了またはキャンセルしてから開始してください");
    return;
  }

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

  let parallel = 1;
  const parallelText = $("parallel").value.trim();
  if (parallelText) {
    if (!/^\d+$/.test(parallelText) || parseInt(parallelText, 10) < 1) {
      showGenError("同時実行数は1以上の整数で入力してください");
      return;
    }
    parallel = parseInt(parallelText, 10);
  }
  if ($("cookie-jar").checked && parallel > 1) {
    showGenError("cookie-jar と 同時実行数(2以上) は同時に指定できません");
    return;
  }
  if ($("no-normal").checked && $("no-abnormal").checked) {
    showGenError("「正常系ケースを生成しない」と「異常系ケースを生成しない」を両方はチェックできません（0件になります）");
    return;
  }

  const outputDir = $("output-dir").value.trim() || dirName(openapiPath);
  if (authConfigEnabled()) {
    try {
      await validateAuthAgainstOpenapi(collectAuthConfig());
    } catch (error) {
      showGenError(error.message);
      return;
    }
  }
  try {
    await invoke("ensure_output_dir", { path: outputDir });
  } catch (e) {
    showGenError(`${e}（「2. 実行設定」の出力先フォルダを確認してください）`);
    return;
  }

  const projectData = buildProjectData({
    openapiPath,
    baseUrl,
    outputDir,
    operations: lastOperations.map((operation) => operation.operationId),
    uncheckedOperations: unchecked,
    setupSqlPath: setupPath,
    teardownSqlPath: teardownPath,
    dbScenariosPath: $("dbscenario-path").value.trim(),
  });
  const caseIds = pendingCaseIds;
  pendingCaseIds = [];
  try {
    await persistSettings();

    if (caseIds.length === 0) {
      tempProjectPath = await invoke("write_config_file", { path: null, data: projectData });
      currentResultPath = null;
      currentCaseMaster = null;
      currentCaseMasterPath = null;
      currentFailedCaseIds = [];
      preparedProjectData = projectData;
      contractPreparationSettings = preparationSnapshot;
      preparedCaseRunId = null;
      preparationCompleted = false;
      preparingCases = true;
      syncPreparedExecutionButtons();
      startRunUi();
      try {
        const { code } = await workflowClient.prepare({
          projectPath: tempProjectPath,
          noNormal: $("no-normal").checked,
          noAbnormal: $("no-abnormal").checked,
        }, { onEvent: handleContractWorkflowEvent });
        finishPrepareUi(code);
      } catch (e) {
        appendLog(`[ERROR] ${e.message || "ケース準備を開始できませんでした"}`);
        finishPrepareUi(3);
      } finally {
        preparingCases = false;
        await cleanupGenTempConfigFiles();
      }
      return;
    }

    const { configPath, authConfigPath } = await writeContractRuntimeConfigs();
    tempProjectPath = await invoke("write_config_file", { path: null, data: projectData });
    currentResultPath = null;
    currentCaseMaster = null;
    currentCaseMasterPath = null;
    preparedCaseRunId = null;
    preparedProjectData = null;
    preparationCompleted = false;
    startRunUi();
    const { code } = await workflowClient.run({
      workflow: "contract",
      projectPath: tempProjectPath,
      runtimeConfigPath: configPath || undefined,
      authConfigPath: authConfigPath || undefined,
      parallel,
      failFast: $("fail-fast").checked,
      persistCookies: $("cookie-jar").checked,
      dryRun: $("dry-run").checked,
      fullBody: $("full-body").checked,
      noNormal: $("no-normal").checked,
      noAbnormal: $("no-abnormal").checked,
      caseIds,
    }, { onEvent: handleContractWorkflowEvent });
    finishRunUi(code);
  } catch (e) {
    appendLog(`[ERROR] ${e.message || "処理を開始できませんでした"}`);
    finishRunUi(3);
  } finally {
    await cleanupGenTempConfigFiles();
  }
});

$("cancel-button").addEventListener("click", async () => {
  await workflowClient.cancel();
});

$("open-result-button").addEventListener("click", async () => {
  if (currentResultPath) {
    // デスクトップ版はOSの関連付けで開き、ブラウザー版はダウンロードする。
    await openPath(currentResultPath).catch(() => {});
  }
});

listen("proc-line", (event) => {
  const { runId, line } = event.payload;
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

});

// Prepared cases must not silently use a destination/options snapshot that the UI no longer shows.
const PREPARATION_FIELDS = ["openapi-path", "base-url", "output-dir", "setup-sql-path", "teardown-sql-path",
  "dbscenario-path", "no-normal", "no-abnormal", "pg-enabled", "pg-host", "pg-port", "pg-dbname", "pg-schema", "pg-user",
  "influx-enabled", "influx-host", "influx-port", "influx-database", "influx-username"];
let contractPreparationSettings = null;
let dbPreparationSettings = null;
function preparationSettings() {
  return JSON.stringify({ fields: PREPARATION_FIELDS.map((id) => {
    const input = $(id);
    return [id, input.type === "checkbox" ? input.checked : input.value.trim()];
  }), excluded: getUncheckedOperationIds().sort() });
}

function invalidateChangedPreparation() {
  const current = preparationSettings();
  const message = "設定が準備時から変更されています。最新の設定で試験ケースを作り直してください。";
  if (preparationCompleted && contractPreparationSettings !== current) {
    preparationCompleted = false;
    preparedCaseRunId = null;
    $("case-review-message").textContent = message;
    setStatus(message, "warn");
    syncPreparedExecutionButtons();
  }
  if (dbScenarioPreparationCompleted && dbPreparationSettings !== current) {
    dbScenarioPreparationCompleted = false;
    dbScenarioPreparedRunId = null;
    $("dbscenario-case-review-message").textContent = message;
    setDbScenarioStatus(message, "warn");
    syncDbPreparedExecutionButtons();
  }
}
for (const id of PREPARATION_FIELDS) {
  $(id).addEventListener("input", invalidateChangedPreparation);
  $(id).addEventListener("change", invalidateChangedPreparation);
}
$("operations-list").addEventListener("change", invalidateChangedPreparation);

// ---------- 初期化 ----------

loadSettingsIntoForm();
loadRuntimeDiagnosis();
loadAppVersion();

$("contract-response-empty").addEventListener("change", () => { $("contract-response-schema-builder").hidden = $("contract-response-empty").checked; });
