import { beforeEach, describe, expect, test, vi } from "vitest";
import { initDbScenarioEditor, buildDbScenario, buildDbScenarios } from "../src/db-scenario-editor.js";

const initialBody = document.body.innerHTML;
beforeEach(() => { document.body.innerHTML = initialBody; });

test("InfluxDBの更新用初期値を型付きで入力し準備・後片付けを設定する", async () => {
  const operation = { ...createUserOperation, method: "PATCH" };
  const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [operation] : "db-checks.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
  await editor.load("openapi.json"); selectOperation("createUser");
  const engine = document.getElementById("dbscenario-editor-engine"); engine.value = "influxdb"; engine.dispatchEvent(new window.Event("change"));
  document.getElementById("dbscenario-editor-table").value = "measure";
  document.getElementById("dbscenario-editor-influx-time").value = "2026-01-01T00:00:00Z";
  const mapping = document.querySelector('#dbscenario-editor-write-mappings tr[data-field-path="email"]');
  mapping.querySelector('[data-api-value]').value = "new@example.com";
  mapping.querySelector('input[aria-label="DBカラム"]').value = "email";
  const fixture = document.getElementById("dbscenario-editor-influx-fixture");
  expect(fixture.checked).toBe(false);
  fixture.click();
  expect(document.getElementById("dbscenario-editor-influx-fixture-panel").hidden).toBe(false);
  expect(document.getElementById("dbscenario-editor-influx-seeds-panel").hidden).toBe(false);
  document.getElementById("dbscenario-editor-add-scenario").click();
  expect(document.getElementById("dbscenario-editor-status").textContent).toContain("初期フィールドを1件以上");
  for (const [name, type, value] of [["email", "string", "old@example.com"], ["reading", "float", "1.25"], ["enabled", "boolean", "false"]]) {
    document.getElementById("dbscenario-editor-influx-add-seed").click();
    const row = document.querySelector("#dbscenario-editor-influx-seeds tr:last-child");
    row.querySelector("[data-seed-name]").value = name;
    row.querySelector("[data-seed-type]").value = type;
    row.querySelector("[data-seed-value]").value = value;
  }
  document.getElementById("dbscenario-editor-add-scenario").click();
  const saved = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
  expect(saved.influx_mutation.fixture.fields).toEqual({
    email: { type: "string", value: "old@example.com" }, reading: { type: "float", value: 1.25 }, enabled: { type: "boolean", value: false },
  });
});

const createUserOperation = {
  operationId: "createUser",
  method: "POST",
  path: "/users",
  successStatus: "201",
  parameters: [],
  requestSchema: {
    type: "object",
    required: ["email", "profile"],
    properties: {
      email: { type: "string", format: "email" },
      profile: {
        type: "object",
        required: ["name"],
        properties: {
          name: { type: "string" },
          nickname: { type: "string" },
        },
      },
      id: { type: "integer", readOnly: true },
    },
  },
  responseSchema: {
    type: "object",
    properties: {
      id: { type: "integer" },
      email: { type: "string", format: "email" },
    },
  },
};

function selectOperation(operationId) {
  const select = document.getElementById("dbscenario-editor-operation");
  select.value = operationId;
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
}

describe("DBシナリオエディター", () => {
  test("OpenAPI項目の行を固定表示し、人がDB列を設定してPOST確認を生成する", async () => {
    const invoke = vi.fn(async (_command, payload) => {
      if (payload?.command === "list_db_scenario_operations") return [createUserOperation];
      return "db-checks.yaml";
    });
    const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
    await editor.load("openapi.json");
    selectOperation("createUser");

    const rows = [...document.querySelectorAll("#dbscenario-editor-write-mappings tr[data-field-path]")];
    expect(rows.map((row) => row.dataset.fieldPath)).toEqual(["email", "profile.name", "profile.nickname"]);
    expect(rows[0].textContent).toContain("string・必須");
    expect(rows[1].textContent).toContain("string・必須");
    expect(document.querySelector("#dbscenario-editor-write-panel button[data-add-row]")).toBeNull();

    document.getElementById("dbscenario-editor-name").value = "新規ユーザーを保存";
    document.getElementById("dbscenario-editor-table").value = "users";
    const emailRow = rows.find((row) => row.dataset.fieldPath === "email");
    emailRow.querySelector("[data-api-value]").value = "new@example.com";
    const nameRow = rows.find((row) => row.dataset.fieldPath === "profile.name");
    nameRow.querySelector("[data-api-value]").value = "New User";
    const nicknameRow = rows.find((row) => row.dataset.fieldPath === "profile.nickname");
    const includeNickname = nicknameRow.querySelector("input[data-include-field]");
    includeNickname.checked = true;
    includeNickname.dispatchEvent(new window.Event("change", { bubbles: true }));
    nicknameRow.querySelector("[data-api-value]").value = "new";
    for (const row of rows) {
      const column = row.querySelector('input[aria-label="DBカラム"]');
      if (row.dataset.fieldPath === "email") {
        column.value = "email";
        row.querySelector('input[aria-label="保存後の照合に使う"]').checked = true;
      } else if (row.dataset.fieldPath === "profile.name") {
        column.value = "name";
      }
    }

    document.getElementById("dbscenario-editor-add-scenario").click();

    const generated = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
    expect(generated.request.body).toEqual({
      email: "new@example.com",
      profile: { name: "New User", nickname: "new" },
    });
    expect(generated.db_check).toEqual({
      table: "users",
      where: { email: "new@example.com" },
      expect: { exists: true, columns: { email: "new@example.com", name: "New User" } },
    });
  });

  test("POSTのレスポンスIDで作成行を特定できる", async () => {
    const invoke = vi.fn(async (_command, payload) => {
      if (payload?.command === "list_db_scenario_operations") return [createUserOperation];
      return "db-checks.yaml";
    });
    const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
    await editor.load("openapi.json");
    selectOperation("createUser");

    document.getElementById("dbscenario-editor-name").value = "採番IDで照合";
    document.getElementById("dbscenario-editor-table").value = "users";
    const emailRow = [...document.querySelectorAll("#dbscenario-editor-write-mappings tr")]
      .find((row) => row.dataset.fieldPath === "email");
    emailRow.querySelector('input[aria-label="DBカラム"]').value = "email";
    document.getElementById("dbscenario-editor-response-row-path").value = "id";
    document.getElementById("dbscenario-editor-response-row-column").value = "id";

    document.getElementById("dbscenario-editor-add-scenario").click();
    const generated = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
    expect(generated.db_check.where).toEqual({ id: "{{response.id}}" });
    expect(generated.db_check.expect.columns.email).toBe("test@example.com");
  });

  test("数値・boolean・配列の値を型どおりにJSONへ組み立てる", async () => {
    const operation = {
      operationId: "createBatch",
      method: "POST",
      path: "/batches",
      successStatus: "201",
      parameters: [],
      requestSchema: {
        type: "object",
        required: ["count", "active", "tags"],
        properties: {
          count: { type: "integer", minimum: 1, maximum: 10 },
          active: { type: "boolean" },
          tags: { type: "array", items: { type: "string" }, minItems: 1 },
        },
      },
    };
    const invoke = vi.fn(async (_command, payload) => {
      if (payload?.command === "list_db_scenario_operations") return [operation];
      return "db-checks.yaml";
    });
    const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
    await editor.load("openapi.json");
    selectOperation("createBatch");

    document.getElementById("dbscenario-editor-name").value = "batchを保存";
    document.getElementById("dbscenario-editor-table").value = "batches";
    const rows = [...document.querySelectorAll("#dbscenario-editor-write-mappings tr[data-field-path]")];
    const countRow = rows.find((row) => row.dataset.fieldPath === "count");
    const count = countRow.querySelector("[data-api-value]");
    expect(count.type).toBe("number");
    expect(count.min).toBe("1");
    expect(count.max).toBe("10");
    count.value = "7";
    rows.find((row) => row.dataset.fieldPath === "active").querySelector("[data-api-value]").value = "true";
    rows.find((row) => row.dataset.fieldPath === "tags").querySelector("[data-api-value]").value = '["a", "b"]';
    countRow.querySelector('input[aria-label="DBカラム"]').value = "count";
    countRow.querySelector('input[aria-label="保存後の照合に使う"]').checked = true;

    document.getElementById("dbscenario-editor-add-scenario").click();

    const generated = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
    expect(generated.request.body).toEqual({ count: 7, active: true, tags: ["a", "b"] });
  });

  test("POST後の片付けは明示的に有効にした場合だけ生成する", async () => {
    const invoke = vi.fn(async (_command, payload) => {
      if (payload?.command === "list_db_scenario_operations") return [createUserOperation];
      return "db-checks.yaml";
    });
    const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
    await editor.load("openapi.json");
    selectOperation("createUser");

    document.getElementById("dbscenario-editor-name").value = "片付けるPOST試験";
    document.getElementById("dbscenario-editor-table").value = "users";
    const emailRow = [...document.querySelectorAll("#dbscenario-editor-write-mappings tr")]
      .find((row) => row.dataset.fieldPath === "email");
    emailRow.querySelector("[data-api-value]").value = "cleanup@example.com";
    emailRow.querySelector('input[aria-label="DBカラム"]').value = "email";
    emailRow.querySelector('input[aria-label="保存後の照合に使う"]').checked = true;
    document.getElementById("dbscenario-editor-post-cleanup-enabled").checked = true;
    document.getElementById("dbscenario-editor-post-cleanup-primary-key").value = "id";

    document.getElementById("dbscenario-editor-add-scenario").click();

    const generated = JSON.parse(document.querySelector("#dbscenario-editor-scenario-list pre").textContent);
    expect(generated.cleanup).toEqual({
      table: "users",
      primary_key: "id",
      where: { email: "cleanup@example.com" },
    });
  });

  test("GETのQuery条件とレスポンス項目の手動対応からDB照合シナリオを作る", () => {
    const operation = {
      operationId: "listUsers",
      method: "GET",
      path: "/users",
      parameters: [{ in: "query", name: "start", required: true }, { in: "query", name: "end" }],
      responseSchema: {
        type: "array",
        items: { type: "object", properties: { id: { type: "integer" }, created_at: { type: "string" } } },
      },
    };
    const generated = buildDbScenario({
      operation,
      name: "期間内ユーザー一覧",
      table: "users",
      queryParams: {},
      pathParams: {},
      responseStatus: 200,
      responseShape: "array",
      responseArrayPath: "$",
      readMappings: [
        { source: "user_id", target: "id" },
        { source: "created_at", target: "created_at" },
      ],
      readFilters: [
        { source: "query", parameter: "start", column: "created_at", operator: ">=" },
        { source: "query", parameter: "end", column: "created_at", operator: "<=" },
      ],
    });

    expect(generated.request.query_params).toEqual({});
    expect(generated.db_response_check).toEqual({
      table: "users",
      fields: { id: "user_id", created_at: "created_at" },
      filters: [
        { source: "query", parameter: "start", column: "created_at", operator: ">=", auto: true, format: null },
        { source: "query", parameter: "end", column: "created_at", operator: "<=", auto: true, format: null },
      ],
      array_path: "$",
    });
  });
});

test("エラー時の変更なし確認をUIから登録でき、正常系の必須入力を強制しない", async () => {
  const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [createUserOperation] : "db-checks.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
  await editor.load("openapi.json");
  selectOperation("createUser");
  const set = (id, value) => { document.getElementById(`dbscenario-editor-${id}`).value = value; };
  set("mode", "unchanged");
  document.getElementById("dbscenario-editor-mode").dispatchEvent(new window.Event("change"));
  expect(document.getElementById("dbscenario-editor-write-panel").hidden).toBe(true);
  expect(document.getElementById("dbscenario-editor-unchanged-panel").hidden).toBe(false);
  set("table", "users"); set("unchanged-body", '{"email":123}');
  set("unchanged-status", "422"); set("unchanged-columns", "id, email"); set("unchanged-where", '{"site_id":1}');
  document.getElementById("dbscenario-editor-add-scenario").click();
  const preview = document.querySelector("#dbscenario-editor-scenario-list pre");
  expect(preview).not.toBeNull();
  const saved = JSON.parse(preview.textContent);
  expect(saved.request.body).toEqual({ email: 123 });
  expect(saved.response_check.expect.status).toBe(422);
  expect(saved.db_unchanged).toEqual([{ table: "users", columns: ["id", "email"], where: { site_id: 1 } }]);
  expect(saved.given).toBeUndefined(); expect(saved.db_check).toBeUndefined();
});

test("DB変更なしのstatusと比較する列を人間が指定しなければ登録しない", () => {
  const form = { operation: createUserOperation, name: "error", table: "users", mode: "unchanged", requestBody: {} };
  expect(() => buildDbScenario(form)).toThrow("HTTP status");
  expect(() => buildDbScenario({ ...form, unchangedStatus: 400 })).toThrow("DB列");
  expect(() => buildDbScenario({ ...form, unchangedStatus: 400, unchangedColumns: "id", unchangedWhere: { id: [] } })).toThrow("単一");
});

test("InfluxDBを選んで変更なし比較の期間とmeasurementを保存する", async () => {
  const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [createUserOperation] : "db-checks.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(async () => "db-checks.yaml"), onSaved: vi.fn() });
  await editor.load("openapi.json");
  selectOperation("createUser");
  const select = document.getElementById("dbscenario-editor-engine"); select.value = "influxdb"; select.dispatchEvent(new window.Event("change"));
  const mode = document.getElementById("dbscenario-editor-mode"); mode.value = "unchanged"; mode.dispatchEvent(new window.Event("change"));
  expect(document.getElementById("dbscenario-editor-influx-period").hidden).toBe(false);
  for (const [id, value] of Object.entries({
    "table": "measure", "unchanged-status": "400", "unchanged-columns": "time, item, value",
    "time-start": "2026-01-01T00:00:00Z", "time-end": "2026-01-02T00:00:00Z",
  })) document.getElementById(`dbscenario-editor-${id}`).value = value;
  document.getElementById("dbscenario-editor-add-scenario").click();
  document.getElementById("dbscenario-editor-save").click();
  await vi.waitFor(() => expect(invoke).toHaveBeenCalledWith("bridge_call", expect.objectContaining({ command: "save_db_scenario_yaml" })));
  const saved = invoke.mock.calls.find((call) => call[1]?.command === "save_db_scenario_yaml")[1].args.scenarios[0];
  expect(saved.db_unchanged[0]).toMatchObject({ engine: "influxdb", table: "measure", time_start: "2026-01-01T00:00:00Z", time_end: "2026-01-02T00:00:00Z" });
  expect(saved).not.toHaveProperty("given");
});

test("InfluxDBのPOSTではAPI項目から保存期待値を生成し、SQLと前提行は不要", async () => {
  const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [createUserOperation] : "db-checks.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(async () => "db-checks.yaml"), onSaved: vi.fn() });
  await editor.load("openapi.json"); selectOperation("createUser");
  const engine = document.getElementById("dbscenario-editor-engine"); engine.value = "influxdb"; engine.dispatchEvent(new window.Event("change"));
  expect(document.getElementById("dbscenario-editor-influx-mutation").hidden).toBe(false);
  expect(document.getElementById("dbscenario-editor-add-scenario").disabled).toBe(false);
  document.getElementById("dbscenario-editor-table").value = "measure";
  document.getElementById("dbscenario-editor-influx-time").value = "2026-01-01T00:00:00Z";
  document.getElementById("dbscenario-editor-influx-tags").value = '{"item":"a"}';
  const row = document.querySelector('#dbscenario-editor-write-mappings tr[data-field-path="email"]');
  row.querySelector('[data-api-value]').value = "test@example.com";
  row.querySelector('input[aria-label="DBカラム"]').value = "email";
  document.getElementById("dbscenario-editor-add-scenario").click();
  expect(document.getElementById("dbscenario-editor-status").textContent).toContain("1件の対応を追加");
  document.getElementById("dbscenario-editor-save").click();
  await vi.waitFor(() => expect(invoke).toHaveBeenCalledWith("bridge_call", expect.objectContaining({ command: "save_db_scenario_yaml" })));
  const saved = invoke.mock.calls.find((call) => call[1]?.command === "save_db_scenario_yaml")[1].args.scenarios[0];
  expect(saved.influx_mutation).toMatchObject({ action: "insert", measurement: "measure", fields: { email: "test@example.com" }, tags: { item: "a" } });
  expect(saved).not.toHaveProperty("given");
  expect(saved).not.toHaveProperty("db_check");
});

const lookupOperation = {
  operationId: "measureLookup", method: "GET", path: "/measure", parameters: [],
  requestSchema: { type: "object", required: ["location_id"], properties: { location_id: { type: "string" } } },
  responseSchema: { type: "object", properties: { result: { type: "array", items: {
    type: "object", properties: { value: { type: "number" } },
  } } } },
};
const lookupRule = { engine: "postgres", table: "t_site", match_column: "location_id", value_column: "site_id",
  cardinality: "many", value_type: "string", on_empty: "unverified" };
const lookupForm = { operation: lookupOperation, engine: "influxdb", name: "locationから計測値", table: "measure",
  requestBody: { location_id: "A" }, responseStatus: "200", responseShape: "array", responseArrayPath: "result",
  readMappings: [{ source: "value", target: "value" }],
  readFilters: [{ source: "body", parameter: "location_id", column: "site_id", operator: "in", lookup: lookupRule }],
};

test("別DBの取得値を照合条件に使い、APIへは元のlocation_idを送る定義を保存する", () => {
  const scenario = buildDbScenario(lookupForm);
  expect(scenario.request.body).toEqual({ location_id: "A" });
  expect(scenario.db_response_check.filters[0]).toMatchObject({ operator: "in", auto: false, lookup: lookupRule });
  expect(scenario.db_response_check.engine).toBe("influxdb");
});

test("別DB参照の0件動作と比較方法は明示した設定のみ許可する", () => {
  const build = (lookup, operator = "in") => buildDbScenario({ ...lookupForm,
    readFilters: [{ ...lookupForm.readFilters[0], operator, lookup }] });
  expect(() => build({ ...lookupRule, on_empty: "status", empty_status: "" })).toThrow("400〜499");
  expect(build({ ...lookupRule, on_empty: "status", empty_status: "404" }).db_response_check.filters[0].lookup.empty_status).toBe(404);
  expect(() => build(lookupRule, "=")).toThrow("全件ならIN");
  expect(() => build({ ...lookupRule, table: "t_site;DROP TABLE t" })).toThrow();
});

test("UIの固定項目行から参照元DBと取得列を入力できる", async () => {
  const invoke = vi.fn(async (_command, payload) => payload?.command === "list_db_scenario_operations" ? [lookupOperation] : "checks.yaml");
  const editor = initDbScenarioEditor({ invoke, saveDialog: vi.fn(), onSaved: vi.fn() });
  await editor.load("openapi.json"); selectOperation("measureLookup");
  document.getElementById("dbscenario-editor-table").value = "measure";
  document.getElementById("dbscenario-editor-response-shape").value = "array";
  document.getElementById("dbscenario-editor-response-array-path").value = "result";
  document.getElementById("dbscenario-editor-response-array-path").dispatchEvent(new window.Event("input"));
  const row = document.querySelector('#dbscenario-editor-read-filters tr[data-parameter-name="location_id"]');
  row.querySelector("[data-request-value]").value = '"A"';
  row.querySelector("[data-db-column]").value = "site_id";
  row.querySelector("[data-lookup-enabled]").click();
  expect(row.querySelector(".db-lookup-fields").hidden).toBe(false);
  for (const [name, value] of Object.entries(lookupRule)) {
    const input = row.querySelector(`[data-lookup-field="${name}"]`);
    input.value = value; input.dispatchEvent(new window.Event("change"));
  }
  expect(row.querySelector('select[aria-label="DBとの比較条件"]').value).toBe("in");
  expect(row.querySelector('select[aria-label="DBとの比較条件"]').disabled).toBe(true);
  const mapping = document.querySelector('#dbscenario-editor-read-mappings input[data-db-column]');
  mapping.value = "value";
  document.getElementById("dbscenario-editor-add-scenario").click();
  const saved = document.querySelector("#dbscenario-editor-scenario-list pre");
  expect(saved, document.getElementById("dbscenario-editor-status").textContent).not.toBeNull();
  expect(JSON.parse(saved.textContent).db_response_check.filters[0].lookup).toEqual(lookupRule);
});


test("参照結果のIN比較を、送信文字列の配列展開と混同しない", () => {
  const scenarios = buildDbScenarios({ ...lookupForm, expandCombinations: true });
  expect(scenarios).toHaveLength(1);
  expect(scenarios[0].request.body.location_id).toBe("A");
});

test("Queryの別DB参照でも送信値を保持し、自動生成値で置換しない", () => {
  const form = { ...lookupForm, requestBody: {}, queryParams: { location_id: "A" },
    operation: { ...lookupOperation, requestSchema: {}, parameters: [{ in: "query", name: "location_id", required: true, schema: { type: "string" } }] },
    readFilters: [{ ...lookupForm.readFilters[0], source: "query" }],
  };
  expect(buildDbScenario(form).request.query_params).toEqual({ location_id: "A" });
  expect(() => buildDbScenario({ ...form, queryParams: {} })).toThrow("送信値");
});
