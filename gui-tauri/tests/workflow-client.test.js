import { describe, expect, test, vi } from "vitest";
import { createWorkflowClient } from "../src/workflow-client.js";

function createHarness() {
  const handlers = new Map();
  const invoke = vi.fn(async () => undefined);
  const listen = vi.fn(async (name, handler) => {
    handlers.set(name, handler);
    return () => handlers.delete(name);
  });
  return {
    invoke,
    listen,
    emitLine(payload) { handlers.get("proc-line")?.({ payload }); },
    emitDone(payload) { handlers.get("proc-done")?.({ payload }); },
  };
}

const nextTask = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("workflow client", () => {
  test("forwards parsed workflow events for its active run only", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const onEvent = vi.fn();
    const completion = client.run(
      { workflow: "contract", projectPath: "C:/work/project.json" },
      { onEvent },
    );
    await nextTask();

    harness.emitLine({ runId: "other", line: '{"type":"progress","current":1,"total":9}' });
    harness.emitLine({ runId: client.runId(), line: '{"type":"progress","current":2,"total":5}' });
    harness.emitDone({ runId: client.runId(), code: 0 });

    await expect(completion).resolves.toEqual({ code: 0 });
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ current: 2, total: 5 }));
  });

  test("turns non-JSON child output into a log event", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const onEvent = vi.fn();
    const completion = client.run({ workflow: "contract", projectPath: "C:/p.json" }, { onEvent });
    await Promise.resolve();

    harness.emitLine({ runId: client.runId(), line: "通常ログ" });
    harness.emitDone({ runId: client.runId(), code: 0 });

    await completion;
    expect(onEvent).toHaveBeenCalledWith({ type: "log", level: "info", message: "通常ログ" });
  });

  test("clears active state and exposes a friendly error when launch fails", async () => {
    const harness = createHarness();
    harness.invoke.mockRejectedValueOnce(new Error("spawn failed"));
    const client = createWorkflowClient(harness);

    await expect(client.run({ workflow: "contract", projectPath: "C:/p.json" }, {})).rejects.toThrow(
      "処理を開始できませんでした",
    );
    expect(client.isRunning()).toBe(false);
  });

  test("cancels an active run once", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.run({ workflow: "contract", projectPath: "C:/p.json" }, {});
    await Promise.resolve();

    await client.cancel();
    await client.cancel();
    harness.emitDone({ runId: client.runId(), code: 130 });

    await completion;
    expect(harness.invoke).toHaveBeenCalledWith("cancel_script", expect.any(Object));
    expect(harness.invoke.mock.calls.filter(([name]) => name === "cancel_script")).toHaveLength(1);
  });

  test("passes supported runtime settings to either workflow", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.run({
      workflow: "db-scenarios",
      projectPath: "C:/p.json",
      dryRun: true,
      persistCookies: true,
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toEqual(expect.arrayContaining([
      "run-db-scenarios", "--dry-run", "--cookie-jar",
    ]));
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("passes only the requested failed cases when rerunning", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.run({
      workflow: "contract", projectPath: "C:/p.json", caseIds: ["TC-1", "TC-2"],
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toContain("--case-ids");
    expect(payload.args[payload.args.indexOf("--case-ids") + 1]).toBe("TC-1,TC-2");
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("prepares reviewable cases without passing runtime credentials", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.prepare({
      projectPath: "C:/p.json", noNormal: true,
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toEqual(["prepare-contract", "--project", "C:/p.json", "--no-normal"]);
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("executes a prepared case set with an explicit review policy", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.execute({
      projectPath: "C:/p.json", preparedRunId: "20260923-120000-deadbeef",
      runtimeConfigPath: "C:/db.json", allowDraft: true, caseIds: ["TC-1"],
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toEqual(expect.arrayContaining([
      "execute-contract", "--project", "C:/p.json", "--run-id", "20260923-120000-deadbeef",
      "--runtime-config", "C:/db.json", "--allow-draft", "--case-ids", "TC-1",
    ]));
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("prepares DB scenarios without creating a credential file", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.prepareDb({ projectPath: "C:/p.json" });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toEqual(["prepare-db-scenarios", "--project", "C:/p.json"]);
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("executes an approved DB scenario set through its existing runner command", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.executeDb({
      projectPath: "C:/p.json", preparedRunId: "20260923-120000-deadbeef",
      runtimeConfigPath: "C:/db.json", persistCookies: true,
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.args).toEqual(expect.arrayContaining([
      "execute-db-scenarios", "--project", "C:/p.json", "--run-id", "20260923-120000-deadbeef",
      "--runtime-config", "C:/db.json", "--cookie-jar",
    ]));
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });

  test("runs local Schemathesis with bounded options and opt-in mutating methods", async () => {
    const harness = createHarness();
    const client = createWorkflowClient(harness);
    const completion = client.runSchemathesis({
      projectPath: "C:/p.json", authConfigPath: "C:/auth.json",
      includeMutating: true, maxExamples: 7, saveCassette: true,
    });
    await nextTask();

    const [, payload] = harness.invoke.mock.calls.find(([name]) => name === "run_script");
    expect(payload.script).toBe("workflow/cli.py");
    expect(payload.args).toEqual([
      "run-schemathesis", "--project", "C:/p.json", "--max-examples", "7",
      "--include-mutating", "--save-cassette", "--auth-config", "C:/auth.json",
    ]);
    harness.emitDone({ runId: client.runId(), code: 0 });
    await completion;
  });
});
