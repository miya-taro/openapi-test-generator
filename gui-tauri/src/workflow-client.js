function runIdentifier() {
  return `workflow-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseEvent(line) {
  try {
    const value = JSON.parse(line);
    if (value && typeof value === "object" && typeof value.type === "string") return value;
  } catch {
    // JSON Lines以外は既存CLIの通常ログとして表示する。
  }
  return { type: "log", level: "info", message: line };
}

export function createWorkflowClient({ invoke, listen }) {
  let active = null;

  const listenersReady = Promise.all([
    listen("proc-line", (event) => {
      const { runId, line } = event.payload;
      if (active?.runId === runId) active.onEvent?.(parseEvent(line));
    }),
    listen("proc-done", (event) => {
      const { runId, code } = event.payload;
      if (active?.runId !== runId) return;
      const current = active;
      active = null;
      current.resolve({ code });
    }),
  ]);

  function start(command, args, onEvent) {
    if (active) throw new Error("すでに試験を実行中です。完了またはキャンセルしてから開始してください。");
    const runId = runIdentifier();
    return new Promise((resolve, reject) => {
      active = { runId, resolve, reject, onEvent, cancelled: false };
      listenersReady
        .then(() => invoke("run_script", { runId, script: "workflow/cli.py", args: [command, ...args] }))
        .catch(() => {
          if (active?.runId !== runId) return;
          active = null;
          reject(new Error("処理を開始できませんでした。Pythonの実行環境を確認してください。"));
        });
    });
  }

  return {
    isRunning: () => active !== null,
    runId: () => active?.runId ?? null,
    run({ workflow, projectPath, runtimeConfigPath, authConfigPath, parallel, failFast, persistCookies, dryRun, fullBody, noNormal, noAbnormal, caseIds }, { onEvent } = {}) {
      const command = workflow === "db-scenarios" ? "run-db-scenarios" : "run-contract";
      const args = ["--project", projectPath];
      if (runtimeConfigPath) args.push("--runtime-config", runtimeConfigPath);
      if (authConfigPath) args.push("--auth-config", authConfigPath);
      if (parallel && parallel !== 1) args.push("--parallel", String(parallel));
      if (failFast) args.push("--fail-fast");
      if (persistCookies) args.push("--cookie-jar");
      if (dryRun) args.push("--dry-run");
      if (Array.isArray(caseIds) && caseIds.length) args.push("--case-ids", caseIds.join(","));
      if (workflow === "contract") {
        if (fullBody) args.push("--full-body");
        if (noNormal) args.push("--no-normal");
        if (noAbnormal) args.push("--no-abnormal");
      }

      return start(command, args, onEvent);
    },
    prepare({ projectPath, noNormal, noAbnormal }, { onEvent } = {}) {
      const args = ["--project", projectPath];
      if (noNormal) args.push("--no-normal");
      if (noAbnormal) args.push("--no-abnormal");
      return start("prepare-contract", args, onEvent);
    },
    prepareDb({ projectPath }, { onEvent } = {}) {
      return start("prepare-db-scenarios", ["--project", projectPath], onEvent);
    },
    execute({ projectPath, preparedRunId, runtimeConfigPath, authConfigPath, parallel, failFast, persistCookies, dryRun, fullBody, allowDraft, caseIds }, { onEvent } = {}) {
      const args = ["--project", projectPath, "--run-id", preparedRunId];
      if (runtimeConfigPath) args.push("--runtime-config", runtimeConfigPath);
      if (authConfigPath) args.push("--auth-config", authConfigPath);
      if (parallel && parallel !== 1) args.push("--parallel", String(parallel));
      if (failFast) args.push("--fail-fast");
      if (persistCookies) args.push("--cookie-jar");
      if (dryRun) args.push("--dry-run");
      if (fullBody) args.push("--full-body");
      if (allowDraft) args.push("--allow-draft");
      if (Array.isArray(caseIds) && caseIds.length) args.push("--case-ids", caseIds.join(","));
      return start("execute-contract", args, onEvent);
    },
    executeDb({ projectPath, preparedRunId, runtimeConfigPath, authConfigPath, persistCookies, dryRun, allowDraft, caseIds }, { onEvent } = {}) {
      const args = [
        "--project", projectPath,
        "--run-id", preparedRunId,
      ];
      if (runtimeConfigPath) args.push("--runtime-config", runtimeConfigPath);
      if (authConfigPath) args.push("--auth-config", authConfigPath);
      if (persistCookies) args.push("--cookie-jar");
      if (dryRun) args.push("--dry-run");
      if (allowDraft) args.push("--allow-draft");
      if (Array.isArray(caseIds) && caseIds.length) args.push("--case-ids", caseIds.join(","));
      return start("execute-db-scenarios", args, onEvent);
    },
    runSchemathesis({ projectPath, authConfigPath, includeMutating = false, maxExamples = 10, saveCassette = false }, { onEvent } = {}) {
      const args = ["--project", projectPath, "--max-examples", String(maxExamples)];
      if (includeMutating) args.push("--include-mutating");
      if (saveCassette) args.push("--save-cassette");
      if (authConfigPath) args.push("--auth-config", authConfigPath);
      return start("run-schemathesis", args, onEvent);
    },
    async cancel() {
      if (!active || active.cancelled) return;
      active.cancelled = true;
      await invoke("cancel_script", { runId: active.runId });
    },
  };
}
