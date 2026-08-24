import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

function $(id) {
  return document.getElementById(id);
}

// ---------- 設定の読み込み/保存（PySide6版と同じ設定ファイルを共有） ----------

let settings = {};

async function loadSettingsIntoForm() {
  settings = await invoke("load_settings");
  $("openapi-path").value = settings.shared_openapi_path || "";
  $("config-path").value = settings.shared_config_path || "";
  $("output-dir").value = settings.gen_output_dir || "";
  $("base-url").value = settings.gen_base_url || "";
  $("auth-config-path").value = settings.gen_auth_config_path || "";
  $("setup-sql-path").value = settings.gen_setup_path || "";
  $("teardown-sql-path").value = settings.gen_teardown_path || "";
  $("dry-run").checked = !!settings.gen_dry_run;
  $("full-body").checked = !!settings.gen_full_body;
  $("fail-fast").checked = !!settings.gen_fail_fast;
  $("health-check-enabled").checked = !!settings.shared_health_check_enabled;
  await refreshOperationsList({ keepExcluded: true });
}

async function persistSettings() {
  settings.shared_openapi_path = $("openapi-path").value.trim();
  settings.shared_config_path = $("config-path").value.trim();
  settings.gen_output_dir = $("output-dir").value.trim();
  settings.gen_base_url = $("base-url").value.trim();
  settings.gen_auth_config_path = $("auth-config-path").value.trim();
  settings.gen_setup_path = $("setup-sql-path").value.trim();
  settings.gen_teardown_path = $("teardown-sql-path").value.trim();
  settings.gen_dry_run = $("dry-run").checked;
  settings.gen_full_body = $("full-body").checked;
  settings.gen_fail_fast = $("fail-fast").checked;
  settings.shared_health_check_enabled = $("health-check-enabled").checked;
  settings.gen_excluded_operations = getUncheckedOperationIds().join(",");
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

for (const li of document.querySelectorAll("#sidebar li[data-page]")) {
  li.addEventListener("click", () => {
    document.querySelectorAll("#sidebar li").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".page").forEach((el) => el.classList.remove("active"));
    li.classList.add("active");
    $(`page-${li.dataset.page}`).classList.add("active");
  });
}

// ---------- openapi.json / DB接続設定（共有ヘッダー） ----------

$("browse-openapi").addEventListener("click", () =>
  browseFile("openapi-path", [{ name: "JSON", extensions: ["json"] }], () =>
    refreshOperationsList({ keepExcluded: false }),
  ),
);
$("browse-config").addEventListener("click", () =>
  browseFile("config-path", [{ name: "JSON", extensions: ["json"] }]),
);
// ダイアログを使わず直接入力/貼り付けした場合にも一覧を更新する。
$("openapi-path").addEventListener("change", () => refreshOperationsList({ keepExcluded: false }));

// ---------- 出力先フォルダ / 認証設定 / setup・teardown SQL ----------

$("browse-output-dir").addEventListener("click", () => browseDir("output-dir"));
$("browse-auth-config").addEventListener("click", () =>
  browseFile("auth-config-path", [{ name: "JSON", extensions: ["json"] }]),
);
$("browse-setup-sql").addEventListener("click", () =>
  browseFile("setup-sql-path", [{ name: "SQL", extensions: ["sql"] }]),
);
$("browse-teardown-sql").addEventListener("click", () =>
  browseFile("teardown-sql-path", [{ name: "SQL", extensions: ["sql"] }]),
);

// ---------- 対象APIチェックリスト ----------

let lastOperations = [];

async function refreshOperationsList({ keepExcluded }) {
  const path = $("openapi-path").value.trim();
  const container = $("operations-list");
  if (!path) {
    container.innerHTML = '<div class="op-empty">openapi.jsonを選択すると一覧が表示されます</div>';
    lastOperations = [];
    return;
  }

  let ops;
  try {
    ops = await invoke("bridge_call", { command: "list_operations", args: { path } });
  } catch (e) {
    container.innerHTML = `<div class="op-empty">読み込みに失敗しました: ${e}</div>`;
    lastOperations = [];
    return;
  }

  lastOperations = ops || [];
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
    row.innerHTML = `<input type="checkbox" data-op-id="${op.operationId}" ${checked ? "checked" : ""}/>
      <span class="op-method">${op.method}</span><span>${op.path}</span>
      <span style="color:var(--text-muted)">(${op.operationId})</span>`;
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
  const openapiPath = $("openapi-path").value.trim();
  const baseUrl = $("base-url").value.trim();
  if (!openapiPath) {
    alert("openapi.json を選択してください");
    return;
  }
  if (!baseUrl) {
    alert("Base URL を入力してください");
    return;
  }

  const unchecked = getUncheckedOperationIds();
  if (lastOperations.length > 0 && unchecked.length === lastOperations.length) {
    alert("対象APIを少なくとも1つ選択してください");
    return;
  }

  const configPath = $("config-path").value.trim();
  const setupPath = $("setup-sql-path").value.trim();
  const teardownPath = $("teardown-sql-path").value.trim();
  if ((setupPath || teardownPath) && !configPath) {
    alert("試験前SQL または 試験後SQL を指定する場合は DB接続設定 が必要です");
    return;
  }

  await persistSettings();

  const outputDir = $("output-dir").value.trim() || dirName(openapiPath);
  const specPath = joinPath(outputDir, "試験仕様.xlsx");
  const casesPath = joinPath(outputDir, "test_cases.json");
  const resultPath = joinPath(outputDir, "試験仕様_result.xlsx");

  const genArgs = [openapiPath, "-o", casesPath, "--excel-output", specPath];
  if (unchecked.length > 0) genArgs.push("--exclude-ops", unchecked.join(","));

  const runArgs = [specPath, openapiPath, "--base-url", baseUrl, "--output", resultPath];
  if (!$("health-check-enabled").checked) runArgs.push("--skip-health-check");
  const authConfigPath = $("auth-config-path").value.trim();
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
});

// ---------- 初期化 ----------

loadSettingsIntoForm();
