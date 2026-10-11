import { describe, expect, test, vi } from "vitest";
import { initDbScenarioEditor, buildDbScenario } from "../src/db-scenario-editor.js";

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
