import { readFileSync } from "node:fs";
import { describe, expect, test, vi } from "vitest";
import { buildDbScenarios, initDbScenarioEditor } from "../src/db-scenario-editor.js";

const api = JSON.parse(readFileSync("../examples/measure-get-openapi.json", "utf8"));
const op = api.paths["/v1/result/measure/get"].get;
const operation = {
  operationId: op.operationId, method: "GET", path: "/v1/result/measure/get",
  requestSchema: op.requestBody.content["application/json"].schema,
  responseSchema: op.responses["200"].content["application/json"].schema,
  successStatus: "200", parameters: [],
};

function form() {
  const filter = (parameter, column, operator, group = null) => ({ source: "body", parameter, column, operator, group });
  return {
    operation, name: "測定結果", table: "measurements", expandCombinations: true,
    requestBody: { site_id: 1, location_id: "B", start: "2026-01-01T00:00:00Z", end: "2026-01-03T00:00:00Z", items: ["temperature", "humidity"] },
    responseStatus: 200, responseShape: "array", responseArrayPath: "result",
    readMappings: [{ source: "measured_at", target: "time" }, { source: "item_name", target: "item" }, { source: "measured_value", target: "value" }],
    readFilters: [filter("site_id", "site_id", "=", "A"), filter("location_id", "location_id", "=", "A"),
      filter("start", "measured_at", ">="), filter("end", "measured_at", "<="), filter("items", "item_name", "in")],
  };
}

describe("測定結果APIのDB試験組み合わせ", () => {
  test("拠点3通り×期間2通り×items3通りを人の指定値から作る", () => {
    const input = form();
    const cases = buildDbScenarios(input);
    expect(cases).toHaveLength(18);
    expect(new Set(cases.map((item) => JSON.stringify(item.request.body))).size).toBe(18);
    expect(new Set(cases.map((item) => item.name)).size).toBe(18);
    for (const item of cases) {
      const body = item.request.body;
      expect(Object.hasOwn(body, "site_id") || Object.hasOwn(body, "location_id")).toBe(true);
      expect(Object.hasOwn(body, "start")).toBe(Object.hasOwn(body, "end"));
      expect(body.items.length).toBeGreaterThan(0);
      expect(item.response_check.expect.status).toBe(200);
      expect(item.db_response_check.fields).toEqual({ time: "measured_at", item: "item_name", value: "measured_value" });
    }
    expect(input.requestBody.items).toEqual(["temperature", "humidity"]);
    expect(input.requestBody).toHaveProperty("start");
  });

  test("組み合わせ生成を外すと入力した1リクエストだけになる", () => {
    const input = form();
    input.expandCombinations = false;
    expect(buildDbScenarios(input)).toHaveLength(1);
  });

  test("組み合わせに必要なDB値を推測しない", () => {
    const input = form();
    delete input.requestBody.location_id;
    expect(() => buildDbScenarios(input)).toThrow("組み合わせ用に「location_id」の値を入力");
  });

  test("DB条件に未対応の送信項目を黙って無視しない", () => {
    const input = form();
    input.readFilters = input.readFilters.filter((item) => item.parameter !== "items");
    expect(() => buildDbScenarios(input)).toThrow("Body「items」の値をDB検索条件に対応付け");
  });

  test("配列のminItemsを破る正常ケースを作らない", () => {
    const input = form();
    input.operation = JSON.parse(JSON.stringify(operation));
    input.operation.requestSchema.properties.items.minItems = 2;
    expect(buildDbScenarios(input)).toHaveLength(6);
  });

  test("重複したIN値で同じリクエストを増やさない", () => {
    const input = form();
    input.requestBody.items = ["temperature", "temperature"];
    expect(buildDbScenarios(input)).toHaveLength(12);
  });

  test("過剰な組み合わせは明示的に止める", () => {
    const input = form();
    input.requestBody.items = Array.from({ length: 11 }, (_, index) => String(index));
    expect(() => buildDbScenarios(input)).toThrow("64件を超え");
  });

  test("存在しない日付を正常な組み合わせに使わない", () => {
    const input = form();
    input.requestBody.start = "2026-02-30T00:00:00Z";
    expect(() => buildDbScenarios(input)).toThrow("タイムゾーンを含む日時");
  });

  test("有効なうるう日と小文字t/zを使える", () => {
    const input = form();
    input.requestBody.start = "2024-02-29t00:00:00z";
    expect(buildDbScenarios(input)).toHaveLength(18);
  });

  test("実画面のチェックと追加操作で18件が登録される", async () => {
    const input = form();
    const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [operation] : "db-checks.yaml");
    const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
    await editor.load("measure-get-openapi.json");
    const select = document.getElementById("dbscenario-editor-operation");
    select.value = operation.operationId;
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    document.getElementById("dbscenario-editor-name").value = input.name;
    document.getElementById("dbscenario-editor-table").value = input.table;
    document.getElementById("dbscenario-editor-expand-combinations").checked = true;
    for (const row of document.querySelectorAll("#dbscenario-editor-read-filters tr[data-parameter-name]")) {
      const name = row.dataset.parameterName;
      const filter = input.readFilters.find((item) => item.parameter === name);
      row.querySelector("input[data-request-value]").value = JSON.stringify(input.requestBody[name]);
      row.querySelector("input[data-db-column]").value = filter.column;
      row.querySelector("select").value = filter.operator;
      row.querySelector("select[data-or-group]").value = filter.group || "";
    }
    for (const row of document.querySelectorAll("#dbscenario-editor-read-mappings tr[data-response-path]")) {
      row.querySelector("input[data-db-column]").value = input.readMappings.find((item) => item.target === row.dataset.responsePath).source;
    }
    document.getElementById("dbscenario-editor-add-scenario").click();
    expect(document.querySelectorAll("#dbscenario-editor-scenario-list pre")).toHaveLength(18);
  });
});
