import { readFileSync } from "node:fs";
import { beforeEach, expect, test, vi } from "vitest";
import { buildInsertScenario, planInsertMappings } from "../src/insert-editor.js";
import { initDbScenarioEditor } from "../src/db-scenario-editor.js";
const spec = JSON.parse(readFileSync("../examples/plan-post-openapi.json"));
const body = JSON.parse(readFileSync("../examples/plan-post-request.json"));
const operation = { ...spec.paths["/v1/plan/set"].post, method: "POST", path: "/v1/plan/set", successStatus: "200", requestSchema: spec.paths["/v1/plan/set"].post.requestBody.content["application/json"].schema, parameters: [] };
const form = () => ({ operation, engine: "postgres", table: "h_plan", name: "保存照合", rowsPath: "plans[].controls[]", primaryKeys: "datetime,created,site_id,use_id", insertStatus: 200, requestBody: body, emptyBody: true, insertMappings: planInsertMappings() });
const html = document.body.innerHTML;
beforeEach(() => { document.body.innerHTML = html; });

test("plan mappings keep original input and express explicit precedence, parent and JSON values", () => {
  const scenario = buildInsertScenario(form());
  expect(scenario.request.body).toEqual(body);
  expect(scenario.db_insert_check.columns.site_id.preferred_path).toBe("site_id");
  expect(scenario.db_insert_check.columns.correct_point.path).toBe("plans[].controls[].correct_point");
  expect(scenario.db_insert_check.columns.fixed.value).toBe(false);
  expect(scenario.response_check.expect.empty_body).toBe(true);
});

test.each([
  { engine: "influxdb" }, { primaryKeys: "missing" }, { rowsPath: "other[]" },
  { insertMappings: [{ column: "id", rule: { kind: "request", path: "bad.path" } }] },
  { insertStatus: 500 },
])("invalid or unsupported insertion configuration cannot be saved %j", (change) => {
  expect(() => buildInsertScenario({ ...form(), ...change })).toThrow();
});

test("actual UI configures and saves PostgreSQL array inserts", async () => {
  const invoke = vi.fn(async (_cmd, args) => args.command === "list_db_scenario_operations" ? [operation] : "saved.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: async () => "saved.yaml", onSaved: async () => {} });
  await editor.load("plan.json");
  const choose = document.getElementById("dbscenario-editor-operation"); choose.value = operation.operationId; choose.dispatchEvent(new window.Event("change"));
  const mode = document.getElementById("dbscenario-editor-mode"); mode.value = "insert_rows"; mode.dispatchEvent(new window.Event("change"));
  expect(document.getElementById("dbscenario-insert-panel").hidden).toBe(false);
  expect(document.getElementById("dbscenario-editor-write-panel").hidden).toBe(true);
  [...document.querySelectorAll("#dbscenario-insert-panel button")].find((b) => b.textContent === "計画保存の対応例を設定").click();
  document.querySelector('#dbscenario-insert-panel [data-insert-field="body"]').value = JSON.stringify(body);
  document.getElementById("dbscenario-editor-add-scenario").click();
  expect(document.getElementById("dbscenario-editor-status").textContent).toContain("対応を追加");
  const saved = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
  expect(saved.db_insert_check.primary_key).toEqual(["datetime", "created", "site_id", "use_id"]);
  expect(saved.request.body.type).toBe("1-1");
});
