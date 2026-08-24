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

  updateActiveOpenapiText();
  updateActiveBaseUrlText();
  updateHcBaseUrlText();
  updateActiveDbConfigText();

  await refreshOperationsList({ keepExcluded: true });
  // ログイン操作の選択はoperation一覧に依存するため、一覧更新後に復元する。
  if (settings.auth_login_op) $("auth-login-op").value = settings.auth_login_op;
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
  $("active-openapi-text").textContent = `openapi.json: ${name}`;
}

function updateActiveBaseUrlText() {
  const url = $("base-url").value.trim();
  $("active-baseurl-text").textContent = `Base URL: ${url || "未設定"}`;
}

function updateHcBaseUrlText() {
  const url = $("base-url").value.trim();
  $("hc-baseurl-text").textContent = `Base URL: ${url || "未設定"}`;
}

for (const evt of ["input", "change"]) {
  $("base-url").addEventListener(evt, updateActiveBaseUrlText);
  $("base-url").addEventListener(evt, updateHcBaseUrlText);
}

$("goto-settings").addEventListener("click", () => showPage("settings"));
$("hc-goto-settings").addEventListener("click", () => showPage("settings"));

// ---------- ヘルスチェック（試験実行とは独立した、任意の疎通確認） ----------

function setHcStatus(text, state) {
  const el = $("hc-status");
  el.textContent = text;
  el.classList.remove("error", "ok");
  if (state) el.classList.add(state);
}

$("hc-run-button").addEventListener("click", async () => {
  const baseUrl = $("base-url").value.trim();
  if (!baseUrl) {
    setHcStatus("Base URL が未設定です（「設定」画面）", "error");
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
  $("active-dbconfig-text").textContent = `DB接続設定: ${parts.length ? parts.join(" / ") : "未設定"}`;
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
$("auth-login-op").addEventListener("change", async () => {
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
  if (filled.length > 0) {
    setAuthConfigStatus(`openapi.jsonから${filled.join("・")}を自動入力しました（内容を確認してください）`, "ok");
  }
});

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

  const outputDir = $("output-dir").value.trim() || dirName(openapiPath);
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
  if (event.payload.runId !== currentRunId) return;
  appendLog(event.payload.line);
});

listen("proc-done", async (event) => {
  if (event.payload.runId !== currentRunId) return;
  const code = event.payload.code;

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
