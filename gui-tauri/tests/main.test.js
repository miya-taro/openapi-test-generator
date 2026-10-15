import { beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { emitTauriEvent, mockInvoke, mockOpen, mockOpenPath, mockSave } from "./setup.js";
import {
  parsePort,
  dirName,
  joinPath,
  requireField,
  dbConfigEnabled,
  collectDbConfig,
  getUncheckedOperationIds,
  feedProgress,
  runSimpleScript,
  runStatusMeaning,
  runOutcomeAdvice,
  loadRuntimeDiagnosis,
  artifactLabel,
  appendArtifact,
  renderCaseMaster,
  buildMappingArgs,
  parseAuthProfiles,
  contractEditorDefaultPath,
  loadAppVersion,
} from "../src/main.js";
import { COPILOT_OPENAPI_PROMPT } from "../src/copilot-openapi-prompt.js";
import { buildCopilotScenarioPrompt } from "../src/copilot-scenario-prompt.js";

beforeAll(async () => {
  // main.js の末尾で呼ばれる loadSettingsIntoForm()（非同期・awaitされない）が
  // フォームの値を書き換え終わるまで、最初のテストの前に一度だけ待つ。
  await new Promise((resolve) => setTimeout(resolve, 0));
});

beforeEach(() => {
  mockInvoke.mockReset();
  mockOpen.mockReset();
  mockOpenPath.mockReset();
  mockSave.mockReset();
  mockInvoke.mockImplementation(async (cmd) => {
    if (cmd === "load_settings") return {};
    return {};
  });
  mockOpen.mockResolvedValue(null);
  mockOpenPath.mockResolvedValue(null);
  mockSave.mockResolvedValue(null);
});

test("レビュー画面は未対応の制約を合格扱いせず表示する", () => {
  renderCaseMaster({ cases: [], coverage: [{ operationId: "op", location: "body", field: "items",
    keyword: "contains", status: "未対応", caseIds: [], detail: "専用ケースなし" }] }, "/tmp/master.json");
  expect(document.querySelector(".coverage-review").textContent).toContain("未対応");
  expect(document.querySelector(".coverage-review").textContent).toContain("試験の合否とは別");
  expect(document.querySelector("#case-review-panel").hidden).toBe(false);
});

// ---------- 5工程の基本導線 ----------

describe("API試験の基本導線", () => {
  test("5工程ナビゲーションと基本入力を表示し、詳細設定は初期状態で閉じている", () => {
    expect(document.querySelectorAll("#workflow-nav [data-step]")).toHaveLength(5);
    expect(document.querySelector("#project-source")).not.toBeNull();
    expect(document.querySelector("#project-source #openapi-path")).not.toBeNull();
    expect(document.querySelector("#project-source #base-url")).not.toBeNull();
    expect(document.querySelector("#project-source #output-dir")).not.toBeNull();
    expect(document.querySelector("#advanced-settings").open).toBe(false);
  });

  test("工程を選ぶと選択した工程だけが現在位置として示される", () => {
    const review = document.querySelector('#workflow-nav [data-step="review"]');
    review.click();

    expect(review.getAttribute("aria-current")).toBe("step");
    expect(document.querySelector('#workflow-nav [data-step="target"]').hasAttribute("aria-current")).toBe(false);
    expect(document.getElementById("page-gen").classList.contains("active")).toBe(true);
  });

  test("実行環境に不足がある場合は利用者向けの確認メッセージを示す", async () => {
    mockInvoke.mockImplementation(async (command) => {
      if (command === "diagnose_runtime") return { pythonAvailable: false };
      return {};
    });

    await loadRuntimeDiagnosis();

    expect(document.getElementById("runtime-status").textContent).toContain("Python");
    expect(document.getElementById("runtime-status").classList.contains("error")).toBe(true);
  });

  test("同梱Pythonが選ばれた場合は実行環境表示に同梱と示す", async () => {
    mockInvoke.mockImplementation(async (command) => {
      if (command === "diagnose_runtime") {
        return {
          pythonAvailable: true,
          pythonVersion: "3.12.9",
          pythonBundled: true,
          workflowAvailable: true,
          generatorAvailable: true,
          runnerAvailable: true,
        };
      }
      return {};
    });

    await loadRuntimeDiagnosis();

    expect(document.getElementById("runtime-status").textContent).toContain("同梱");
  });

  test("アプリのバージョンをサイドバーに表示する", async () => {
    mockInvoke.mockImplementation(async (command) => {
      if (command === "app_version") return "0.1.0";
      return {};
    });

    await loadAppVersion();

    expect(mockInvoke).toHaveBeenCalledWith("app_version", {});
    expect(document.getElementById("app-version").textContent).toBe("v0.1.0");
  });

  test("バージョン取得に失敗した場合も画面表示を壊さない", async () => {
    mockInvoke.mockRejectedValue(new Error("unavailable"));

    await loadAppVersion();

    expect(document.getElementById("app-version").textContent).toBe("バージョン不明");
  });

  test("Schemathesis設定は折りたたまれ、GET-onlyと証跡なしが既定", () => {
    expect(document.getElementById("schemathesis-panel").open).toBe(false);
    expect(document.getElementById("schemathesis-max-examples").value).toBe("10");
    expect(document.getElementById("schemathesis-include-mutating").checked).toBe(false);
    expect(document.getElementById("schemathesis-save-cassette").checked).toBe(false);
    expect(document.getElementById("run-schemathesis-button")).not.toBeNull();
  });

  test("DB準備画面から手動のAPI・DB対応画面へ進める", () => {
    expect(document.getElementById("dbprep-goto-dbscenario")).not.toBeNull();
    expect(document.getElementById("dbprep-php-db-evidence-path")).toBeNull();
    expect(document.getElementById("dbprep-copilot-scenario-prompt-copy")).toBeNull();
  });

  test("権限試験用の認証プロファイル欄は詳細設定にあり、資格情報を設定へ保存しない", () => {
    expect(document.getElementById("auth-profiles")).not.toBeNull();
    document.getElementById("auth-profiles").value = JSON.stringify({
      read_only: { username: "reader", password: "secret" },
    });
    expect(parseAuthProfiles(document.getElementById("auth-profiles").value)).toEqual({
      read_only: { username: "reader", password: "secret" },
    });
    expect(parseAuthProfiles("")).toBeNull();
  });

  test.each(["not-json", "[]", "{\"bad profile\":{}}", "{\"reader\":[]}"])(
    "不正な認証プロファイル定義を拒否する: %s",
    (value) => expect(() => parseAuthProfiles(value)).toThrow(),
  );

  test("Copilot用PHP調査依頼はDB根拠JSONも要求する", () => {
    expect(COPILOT_OPENAPI_PROMPT).toContain("openapi.db-evidence.json");
    expect(COPILOT_OPENAPI_PROMPT).toContain("api-tester.php-db-evidence");
    expect(COPILOT_OPENAPI_PROMPT).toContain("人が確認するまで確定情報にしない");
  });

  test("request/response body schemaの補正UIを仕様確認工程に表示する", () => {
    expect(document.getElementById("body-contract-editor")).not.toBeNull();
    expect(document.getElementById("contract-request-schema-builder")).not.toBeNull();
    expect(document.getElementById("contract-response-schema-builder")).not.toBeNull();
    expect(document.getElementById("contract-editor-status").getAttribute("aria-live")).toBe("polite");
  });

  test("補正仕様は元ファイルと別名で保存する既定パスを作る", () => {
    expect(contractEditorDefaultPath("C:\\api\\openapi.json")).toBe("C:\\api\\openapi.ui-edited.json");
    expect(contractEditorDefaultPath("/api/spec")).toBe("/api/spec.ui-edited.json");
  });

  test("operationを読み込んでbody schemaを補正した別OpenAPIとして試験対象へ切り替える", async () => {
    mockSave.mockResolvedValue("C:\\work\\openapi.ui-edited.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [{ operationId: "createUser", method: "POST", path: "/users" }];
      }
      if (command === "bridge_call" && payload.command === "servers_url") return null;
      if (command === "bridge_call" && payload.command === "load_operation_body_contract") {
        return {
          operationId: "createUser",
          requestBodyRequired: true,
          requestBodySchema: {
            type: "object",
            required: ["profile"],
            properties: {
              profile: {
                type: "object",
                required: ["name"],
                properties: { name: { type: "string", minLength: 1 } },
              },
            },
          },
          responseStatus: "201",
          responseBodySchema: {
            type: "object",
            required: ["id"],
            properties: { id: { type: "integer", minimum: 1 } },
          },
        };
      }
      if (command === "bridge_call" && payload.command === "save_operation_body_contract") {
        return { path: "C:\\work\\openapi.ui-edited.json", operationId: "createUser", responseStatus: "201" };
      }
      return {};
    });
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("openapi-path").dispatchEvent(new window.Event("change"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("contract-operation").value).toBe("createUser");
    expect(document.getElementById("contract-response-status").value).toBe("201");
    expect(document.querySelector("#contract-request-schema-builder [data-role='property-name']").value).toBe("profile");
    expect(document.querySelectorAll("#contract-request-schema-builder .schema-node-property")).toHaveLength(2);

    const requestBuilder = document.getElementById("contract-request-schema-builder");
    const profile = requestBuilder.querySelector(".schema-node-property");
    profile.querySelector('[data-role="add-property"]').click();
    const requestProperties = requestBuilder.querySelectorAll(".schema-node-property");
    const phone = requestProperties[2];
    const phoneName = phone.querySelector('[data-role="property-name"]');
    phoneName.value = "phone";
    phoneName.dispatchEvent(new window.Event("input", { bubbles: true }));
    phone.querySelector('[data-role="schema-type"]').value = "string";
    phone.querySelector('[data-role="schema-type"]').dispatchEvent(new window.Event("change", { bubbles: true }));
    const updatedPhone = requestBuilder.querySelectorAll(".schema-node-property")[2];
    updatedPhone.querySelector('[data-role="constraint-min"]').value = "2";
    updatedPhone.querySelector('[data-role="constraint-min"]').dispatchEvent(new window.Event("input", { bubbles: true }));

    const responseBuilder = document.getElementById("contract-response-schema-builder");
    const responseId = responseBuilder.querySelector(".schema-node-property");
    responseId.querySelector('[data-role="constraint-min"]').value = "10";
    responseId.querySelector('[data-role="constraint-min"]').dispatchEvent(new window.Event("input", { bubbles: true }));
    document.getElementById("contract-save-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockSave).toHaveBeenCalledWith(expect.objectContaining({
      defaultPath: "C:\\work\\openapi.ui-edited.json",
    }));
    expect(mockInvoke).toHaveBeenCalledWith("bridge_call", expect.objectContaining({
      command: "save_operation_body_contract",
      args: expect.objectContaining({
        source_path: "C:\\work\\openapi.json",
        destination_path: "C:\\work\\openapi.ui-edited.json",
        operation_id: "createUser",
        response_status: "201",
        request_body_schema: {
          type: "object",
          required: ["profile"],
          properties: {
            profile: {
              type: "object",
              required: ["name"],
              properties: {
                name: { type: "string", minLength: 1 },
                phone: { type: "string", minLength: 2 },
              },
            },
          },
        },
        response_body_schema: {
          type: "object",
          required: ["id"],
          properties: { id: { type: "integer", minimum: 10 } },
        },
      }),
    }));
    expect(document.getElementById("openapi-path").value).toBe("C:\\work\\openapi.ui-edited.json");
    expect(document.getElementById("contract-editor-status").textContent).toContain("試験対象に設定しました");
  });

  test("Copilot用DBシナリオ依頼に選択済みファイルを差し込む", () => {
    const prompt = buildCopilotScenarioPrompt({
      openapiPath: "C:\\api\\openapi.json",
      mappingPath: "C:\\api\\mapping.yaml",
      scenarioPath: "C:\\api\\scenarios.yaml",
      phpEvidencePath: "C:\\api\\openapi.db-evidence.json",
    });

    expect(prompt).toContain("OpenAPI定義: C:\\api\\openapi.json");
    expect(prompt).toContain("DB対応表: C:\\api\\mapping.yaml");
    expect(prompt).toContain("既存/出力予定のDBシナリオYAML: C:\\api\\scenarios.yaml");
    expect(prompt).toContain("PHP SQL根拠JSON: C:\\api\\openapi.db-evidence.json");
    expect(prompt).not.toContain("<openapi.jsonのパスを指定");
    expect(prompt).toContain("直接参照できないファイルは、添付または #file で参照を求める");
    expect(prompt).toContain("auth_profile");
    expect(prompt).toContain("大量試行、総当たり、遅延ペイロード");
  });

  test("DBシナリオ画面に固定項目表と人が入力するDB列欄がある", () => {
    expect(document.getElementById("dbscenario-editor-request-body")).not.toBeNull();
    expect(document.getElementById("dbscenario-editor-write-mappings")).not.toBeNull();
    expect(document.getElementById("dbscenario-editor-read-filters")).not.toBeNull();
    expect(document.getElementById("dbscenario-editor-read-mappings")).not.toBeNull();
    expect(document.querySelector("#dbscenario-editor-write-panel button[data-add-row]")).toBeNull();
  });

  test("PHP DB根拠JSONは任意引数として対応表生成へ渡せる", () => {
    expect(buildMappingArgs("openapi.json", "db.json", "mapping.yaml", "public", "evidence.json"))
      .toEqual([
        "openapi.json", "--config", "db.json", "-o", "mapping.yaml",
        "--schema", "public", "--php-db-evidence", "evidence.json",
      ]);
    expect(buildMappingArgs("openapi.json", "db.json", "mapping.yaml", "", ""))
      .toEqual(["openapi.json", "--config", "db.json", "-o", "mapping.yaml"]);
  });
});

describe("Schemathesis探索試験", () => {
  const operations = [
    { operationId: "listUsers", method: "GET", path: "/users" },
    { operationId: "createUser", method: "POST", path: "/users" },
    { operationId: "login", method: "POST", path: "/login" },
  ];

  async function prepareProject({ withAuth = false } = {}) {
    let temporaryFileNumber = 0;
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "load_settings" || command === "save_settings" || command === "ensure_output_dir") return {};
      if (command === "bridge_call" && payload.command === "list_operations") return operations;
      if (command === "bridge_call" && payload.command === "servers_url") return null;
      if (command === "write_config_file") {
        temporaryFileNumber += 1;
        return `C:\\temp\\explore-${temporaryFileNumber}.json`;
      }
      return {};
    });
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "http://127.0.0.1:8080";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("openapi-path").dispatchEvent(new window.Event("change"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (withAuth) {
      document.getElementById("auth-enabled").checked = true;
      document.getElementById("auth-enabled").dispatchEvent(new window.Event("change"));
      document.getElementById("auth-login-op").value = "login";
      document.getElementById("auth-body").value = JSON.stringify({ username: "tester", password: "secret-value" });
    }
  }

  test("拒否すると更新系探索を開始しない", async () => {
    await prepareProject();
    document.getElementById("schemathesis-include-mutating").checked = true;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    document.getElementById("run-schemathesis-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("POST/PUT/PATCH/DELETE"));
    expect(mockInvoke.mock.calls.some(([command]) => command === "run_script")).toBe(false);
    expect(mockInvoke.mock.calls.some(([command]) => command === "write_config_file")).toBe(false);
    confirm.mockRestore();
  });

  test("明示確認後だけ更新系を含め、認証情報は一時ファイル経由で渡す", async () => {
    await prepareProject({ withAuth: true });
    document.getElementById("auth-profiles").value = JSON.stringify({
      read_only: { username: "reader", password: "profile-secret" },
    });
    document.getElementById("schemathesis-include-mutating").checked = true;
    document.getElementById("schemathesis-max-examples").value = "5";
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    document.getElementById("run-schemathesis-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const runCall = mockInvoke.mock.calls.find(([command]) => command === "run_script");
    expect(runCall?.[1].args).toEqual([
      "run-schemathesis", "--project", "C:\\temp\\explore-2.json",
      "--max-examples", "5", "--include-mutating", "--auth-config", "C:\\temp\\explore-1.json",
    ]);
    expect(JSON.stringify(runCall?.[1].args)).not.toContain("secret-value");
    expect(mockInvoke.mock.calls.some(([command, payload]) =>
      command === "write_config_file" && payload.data.body?.password === "secret-value"
    )).toBe(true);
    expect(mockInvoke.mock.calls.some(([command, payload]) =>
      command === "write_config_file"
      && payload.data.auth_profiles?.read_only?.password === "profile-secret"
    )).toBe(true);
    expect(JSON.stringify(mockInvoke.mock.calls.find(([command]) => command === "save_settings")?.[1]))
      .not.toContain("profile-secret");

    emitTauriEvent("proc-done", { runId: runCall[1].runId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockInvoke.mock.calls.filter(([command]) => command === "delete_file")).toHaveLength(2);
    confirm.mockRestore();
  });
});

describe("試験ケースマスター成果物", () => {
  test("結果レポートを内部ファイルより先に表示し保存場所は折り畳む", () => {
    const container = document.getElementById('run-artifacts'); container.replaceChildren();
    appendArtifact('run-artifacts', {kind:'junit_xml', path:'result.xml'});
    appendArtifact('run-artifacts', {kind:'result_excel', path:'result.xlsx'});
    appendArtifact('run-artifacts', {kind:'html_report', path:'report.html'});
    expect([...container.children].map(node => node.dataset.artifactKind)).toEqual(['html_report', 'result_excel', 'junit_xml']);
    expect(container.firstElementChild.querySelector('button').textContent).toBe('結果を確認');
    expect(container.firstElementChild.querySelector('details').open).toBe(false);
    expect(container.firstElementChild.textContent).toContain('絞り込めます');
  });
  test("下書きマスターを識別できる日本語名で表示する", () => {
    expect(artifactLabel("case_master_json")).toBe("試験ケースマスター（下書き）");
    expect(artifactLabel("html_report")).toBe("HTML結果レポート");
    expect(artifactLabel("failed_case_ids_json")).toBe("失敗ケースID一覧");
  });

  test("ケースを安全に表示し、レビュー状態を保存できる", async () => {
    const master = {
      format: "api-tester.case-master",
      schemaVersion: 1,
      cases: [{
        caseId: "TC-1", kind: "contract", title: "<img src=x onerror=alert(1)>",
        definition: { request: { method: "GET", path: "/users" } },
        expected: { status: "200" }, reviewStatus: "draft",
      }],
    };
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "save_case_master_reviews") {
        return { ...master, cases: [{ ...master.cases[0], reviewStatus: "reviewed" }] };
      }
      return {};
    });

    renderCaseMaster(master, "C:\\run\\case-master.json");
    const card = document.querySelector('[data-case-id="TC-1"]');
    expect(card.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(card.querySelector("img")).toBeNull();
    card.querySelector("button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockInvoke).toHaveBeenCalledWith("bridge_call", {
      command: "save_case_master_reviews",
      args: { path: "C:\\run\\case-master.json", updates: { "TC-1": "reviewed" } },
    });
    expect(document.querySelector('[data-case-id="TC-1"] .case-review-status').textContent)
      .toContain("レビュー済み");
  });

  test("既存の成果物ボタンからJSONファイルを既定アプリで開く", async () => {
    const path = "C:\\work\\run\\case-master.json";
    appendArtifact("run-artifacts", { kind: "case_master_json", path });

    const item = document.querySelector('[data-artifact-kind="case_master_json"]');
    expect(item.querySelector(".artifact-item-name").textContent).toBe("試験ケースマスター（下書き）");
    item.querySelector("button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(mockOpenPath).toHaveBeenCalledWith(path);
  });
});

describe("プロジェクト保存・復元", () => {
  test("公開設定だけをproject.jsonへ保存する", async () => {
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "https://vm.local/api";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("pg-password").value = "database-secret";
    document.getElementById("auth-body").value = '{"password":"login-secret"}';
    mockSave.mockResolvedValue("C:\\work\\project.json");

    document.getElementById("project-save").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const write = mockInvoke.mock.calls.find(([command]) => command === "write_config_file");
    expect(write?.[1]).toEqual(expect.objectContaining({ path: "C:\\work\\project.json" }));
    expect(JSON.stringify(write?.[1].data)).not.toMatch(/database-secret|login-secret|password|token|cookie/i);
    expect(document.getElementById("project-status").textContent).toContain("保存しました");
  });

  test("project.jsonを開くと公開設定と選択したoperationだけを復元する", async () => {
    mockOpen.mockResolvedValue("C:\\work\\project.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "load_project") {
        return {
          schemaVersion: 1,
          name: "orders",
          openapiPath: "C:\\work\\openapi.json",
          baseUrl: "https://vm.local/api",
          outputDir: "C:\\work\\results",
          selectedOperations: ["getOrders"],
          setupSqlPath: "C:\\work\\setup.sql",
          teardownSqlPath: null,
          dbScenariosPath: "C:\\work\\scenarios.yaml",
        };
      }
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [
          { operationId: "getOrders", method: "GET", path: "/orders" },
          { operationId: "createOrder", method: "POST", path: "/orders" },
        ];
      }
      if (command === "save_settings") return {};
      return {};
    });
    document.getElementById("pg-password").value = "must-not-change";
    document.getElementById("auth-body").value = '{"password":"must-not-change"}';

    document.getElementById("project-open").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("openapi-path").value).toBe("C:\\work\\openapi.json");
    expect(document.getElementById("base-url").value).toBe("https://vm.local/api");
    expect(document.getElementById("setup-sql-path").value).toBe("C:\\work\\setup.sql");
    expect(document.querySelector('[data-op-id="getOrders"]').checked).toBe(true);
    expect(document.querySelector('[data-op-id="createOrder"]').checked).toBe(false);
    expect(document.getElementById("pg-password").value).toBe("must-not-change");
    expect(document.getElementById("auth-body").value).toBe('{"password":"must-not-change"}');
  });
});

describe("Copilotで作ったPHP APIのOpenAPI下書き", () => {
  test("下書きのAPI名やパスをHTMLとして実行しない", async () => {
    const hostile = '<img src=x onerror="window.attack=1">';
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [{ operationId: hostile, method: "GET", path: hostile }];
      }
      return {};
    });
    document.getElementById("openapi-path").value = "C:\\work\\openapi.draft.json";
    document.getElementById("openapi-path").dispatchEvent(new window.Event("change"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.querySelector("#operations-list img")).toBeNull();
    expect(document.querySelector("#operations-list .op-id").textContent).toBe(hostile);
  });

  test("Copilot用プロンプトをコピーできる", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: { writeText } });

    document.getElementById("copilot-prompt-copy").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const prompt = writeText.mock.calls[0][0];
    expect(prompt).toContain("openapi.draft.json");
    expect(prompt).toContain("openapi.review.md");
    expect(prompt).toContain("根拠");
    expect(document.getElementById("copilot-status").textContent).toContain("コピーしました");
  });

  test("不正な下書きは試験対象に反映しない", async () => {
    document.getElementById("openapi-path").value = "C:\\work\\old.json";
    mockOpen.mockResolvedValue("C:\\work\\openapi.draft.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "validate_openapi") return "NG: JSONを解析できません";
      return {};
    });

    document.getElementById("copilot-draft-import").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("openapi-path").value).toBe("C:\\work\\old.json");
    expect(document.getElementById("copilot-status").textContent).toContain("NG:");
    expect(document.getElementById("copilot-draft-apply").disabled).toBe(true);
  });

  test("operationIdが欠けた下書きは確認済みでも採用できない", async () => {
    mockOpen.mockResolvedValue("C:\\work\\openapi.draft.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "validate_openapi") return "OK（operation数: 2）";
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [{ operationId: "getUser", method: "GET", path: "/users/{id}" }];
      }
      return {};
    });

    document.getElementById("copilot-draft-import").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("copilot-status").textContent).toContain("operationId");
    document.getElementById("copilot-draft-reviewed").checked = true;
    document.getElementById("copilot-draft-reviewed").dispatchEvent(new window.Event("change"));
    expect(document.getElementById("copilot-draft-apply").disabled).toBe(true);
  });

  test("operationIdが重複した下書きは採用できない", async () => {
    mockOpen.mockResolvedValue("C:\\work\\openapi.draft.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "validate_openapi") return "OK（operation数: 2）";
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [
          { operationId: "getUser", method: "GET", path: "/users/{id}" },
          { operationId: "getUser", method: "GET", path: "/users" },
        ];
      }
      return {};
    });

    document.getElementById("copilot-draft-import").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("copilot-status").textContent).toContain("operationId");
    expect(document.getElementById("copilot-draft-apply").disabled).toBe(true);
  });

  test("検証済み下書きでも人が確認するまで試験対象に反映しない", async () => {
    document.getElementById("openapi-path").value = "C:\\work\\old.json";
    mockOpen.mockResolvedValue("C:\\work\\openapi.draft.json");
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "validate_openapi") return "OK（operation数: 1）";
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [{ operationId: "getUser", method: "GET", path: "/users/{id}" }];
      }
      return {};
    });

    document.getElementById("copilot-draft-import").click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.getElementById("openapi-path").value).toBe("C:\\work\\old.json");
    expect(document.getElementById("copilot-draft-apply").disabled).toBe(true);
    expect(document.getElementById("copilot-status").textContent).toContain("1件");

    document.getElementById("copilot-draft-reviewed").checked = true;
    document.getElementById("copilot-draft-reviewed").dispatchEvent(new window.Event("change"));
    document.getElementById("copilot-draft-apply").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("openapi-path").value).toBe("C:\\work\\openapi.draft.json");
    expect(document.querySelector('[data-op-id="getUser"]')).not.toBeNull();
  });
});

// ---------- parsePort ----------
// gui-tauri/src/main.js:parsePort。過去に「80abc」のようなゴミ文字混じりの入力を
// 数値として素通りさせてしまうバグがあった箇所（回帰テスト）。

describe("parsePort", () => {
  test("valid numeric string returns an integer", () => {
    expect(parsePort("8080", "PostgreSQL")).toBe(8080);
  });

  test("empty string throws", () => {
    expect(() => parsePort("", "PostgreSQL")).toThrow(/PostgreSQL/);
  });

  test("non-numeric string throws", () => {
    expect(() => parsePort("abc", "PostgreSQL")).toThrow();
  });

  test("trailing garbage characters throw (regression)", () => {
    expect(() => parsePort("80abc", "PostgreSQL")).toThrow();
  });

  test("leading zeros still parse", () => {
    expect(parsePort("080", "PostgreSQL")).toBe(80);
  });
});

// ---------- dirName / joinPath ----------

describe("dirName", () => {
  test("windows backslash path", () => {
    expect(dirName("C:\\a\\b\\c.txt")).toBe("C:\\a\\b");
  });

  test("forward slash path", () => {
    expect(dirName("/a/b/c.txt")).toBe("/a/b");
  });

  test("no separator returns empty string", () => {
    expect(dirName("file.txt")).toBe("");
  });
});

describe("joinPath", () => {
  test("joins with backslash when dir has no trailing separator", () => {
    expect(joinPath("C:\\a", "b.txt")).toBe("C:\\a\\b.txt");
  });

  test("does not double the separator when dir already ends with one", () => {
    expect(joinPath("C:\\a\\", "b.txt")).toBe("C:\\a\\b.txt");
  });

  test("empty dir returns just the name", () => {
    expect(joinPath("", "b.txt")).toBe("b.txt");
  });
});

// ---------- requireField ----------

describe("requireField", () => {
  test("returns the value when non-empty", () => {
    expect(requireField("value", "label")).toBe("value");
  });

  test("throws with the label in the message when empty", () => {
    expect(() => requireField("", "PostgreSQLのhost")).toThrow(/PostgreSQLのhost/);
  });
});

// ---------- dbConfigEnabled / collectDbConfig ----------

describe("dbConfigEnabled / collectDbConfig", () => {
  beforeEach(() => {
    document.getElementById("pg-enabled").checked = false;
    document.getElementById("influx-enabled").checked = false;
    for (const id of ["pg-host", "pg-port", "pg-dbname", "pg-schema", "pg-user", "pg-password"]) {
      document.getElementById(id).value = "";
    }
    for (const id of ["influx-host", "influx-port", "influx-database", "influx-username", "influx-password"]) {
      document.getElementById(id).value = "";
    }
  });

  test("disabled when neither postgres nor influxdb is checked", () => {
    expect(dbConfigEnabled()).toBe(false);
    expect(collectDbConfig()).toEqual({});
  });

  test("enabled when postgres is checked", () => {
    document.getElementById("pg-enabled").checked = true;
    expect(dbConfigEnabled()).toBe(true);
  });

  test("collectDbConfig builds a postgres section from filled fields", () => {
    document.getElementById("pg-enabled").checked = true;
    document.getElementById("pg-host").value = "127.0.0.1";
    document.getElementById("pg-port").value = "5432";
    document.getElementById("pg-dbname").value = "apitester_test";
    document.getElementById("pg-user").value = "postgres";
    document.getElementById("pg-password").value = "secret";

    const config = collectDbConfig();
    expect(config.postgres).toEqual({
      host: "127.0.0.1",
      port: 5432,
      dbname: "apitester_test",
      user: "postgres",
      password: "secret",
    });
    expect(config.influxdb).toBeUndefined();
  });

  test("collectDbConfig throws when a required postgres field is missing", () => {
    document.getElementById("pg-enabled").checked = true;
    document.getElementById("pg-port").value = "5432";
    document.getElementById("pg-dbname").value = "d";
    document.getElementById("pg-user").value = "u";
    // pg-host は空のまま
    expect(() => collectDbConfig()).toThrow(/host/);
  });

  test("collectDbConfig throws when the postgres port is not numeric", () => {
    document.getElementById("pg-enabled").checked = true;
    document.getElementById("pg-host").value = "h";
    document.getElementById("pg-port").value = "not-a-port";
    document.getElementById("pg-dbname").value = "d";
    document.getElementById("pg-user").value = "u";
    expect(() => collectDbConfig()).toThrow();
  });

  test("collectDbConfig omits optional influxdb username/password when blank", () => {
    document.getElementById("influx-enabled").checked = true;
    document.getElementById("influx-host").value = "h";
    document.getElementById("influx-port").value = "8086";
    document.getElementById("influx-database").value = "metrics";

    const config = collectDbConfig();
    expect(config.influxdb).toEqual({ host: "h", port: 8086, database: "metrics" });
    expect(config.influxdb.username).toBeUndefined();
    expect(config.influxdb.password).toBeUndefined();
  });
});

// ---------- getUncheckedOperationIds ----------

describe("getUncheckedOperationIds", () => {
  test("returns operationIds of unchecked checkboxes only", () => {
    const container = document.getElementById("operations-list");
    container.innerHTML = `
      <label class="op-item"><input type="checkbox" data-op-id="getUser" checked /></label>
      <label class="op-item"><input type="checkbox" data-op-id="deleteUser" /></label>
      <label class="op-item"><input type="checkbox" data-op-id="createUser" checked /></label>
    `;
    expect(getUncheckedOperationIds()).toEqual(["deleteUser"]);
  });

  test("returns an empty array when all are checked", () => {
    const container = document.getElementById("operations-list");
    container.innerHTML = `<label class="op-item"><input type="checkbox" data-op-id="getUser" checked /></label>`;
    expect(getUncheckedOperationIds()).toEqual([]);
  });
});

// ---------- feedProgress ----------

describe("feedProgress", () => {
  test("a total-count line resets progress to 0%", () => {
    feedProgress("試験ケース数：4件");
    expect(document.getElementById("run-progress-bar").style.width).toBe("0%");
  });

  test("OK/NG/WARNING/SKIP lines advance progress proportionally", () => {
    feedProgress("試験ケース数：4件");
    feedProgress("  [OK] TC-001 GET /x → 200");
    expect(document.getElementById("run-progress-bar").style.width).toBe("25%");
    feedProgress("  [NG] TC-002 GET /y → 500");
    expect(document.getElementById("run-progress-bar").style.width).toBe("50%");
  });

  test("unrelated log lines do not advance progress", () => {
    feedProgress("シナリオ数：2件");
    feedProgress("  [OK] a");
    const before = document.getElementById("run-progress-bar").style.width;
    feedProgress("[INFO] something unrelated happened");
    expect(document.getElementById("run-progress-bar").style.width).toBe(before);
  });
});

// ---------- runSimpleScript ----------
// gui-tauri/src/main.js:runSimpleScript。invoke("run_script", ...) がfire-and-forgetで
// 呼ばれており、起動自体が失敗した場合にPromiseが永久に解決されないバグがあった箇所
// （回帰テスト）。

describe("runSimpleScript", () => {
  test("resolves with -1 and shows an error when the script fails to launch", async () => {
    mockInvoke.mockImplementation(async (cmd) => {
      if (cmd === "run_script") throw new Error("curl.exe not found");
      return {};
    });
    const statusEl = document.createElement("div");
    statusEl.classList.add("ok"); // 前回成功時のクラスが残っていないことも確認する

    const code = await runSimpleScript("runner/generate_setup_sql.py", ["--config", "c.json"], { statusEl });

    expect(code).toBe(-1);
    expect(statusEl.textContent).toContain("curl.exe not found");
    expect(statusEl.classList.contains("error")).toBe(true);
  });

  test("shows a running status and clears the log before invoking", async () => {
    mockInvoke.mockImplementation(async () => new Promise(() => {})); // 起動には成功し、完了イベントはまだ来ない想定
    const statusEl = document.createElement("div");
    const logEl = document.createElement("div");
    logEl.hidden = true;
    logEl.textContent = "前回の実行ログ";

    runSimpleScript("runner/generate_mapping.py", [], { statusEl, logEl });
    // invoke呼び出し自体は非同期の先頭で行われるため、同期的に反映される初期状態を確認する
    expect(statusEl.textContent).toBe("実行中...");
    expect(logEl.hidden).toBe(false);
    expect(logEl.textContent).toBe("");
  });
});

// ---------- 統一ワークフロー ----------

describe("統一ワークフローによる契約試験", () => {
  test("ログイン設定とOpenAPIの項目が違う場合は試験ケースを作らない", async () => {
    document.getElementById("gen-error").scrollIntoView = vi.fn();
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "bridge_call" && payload.command === "list_operations") {
        return [{ operationId: "login", method: "POST", path: "/v1/auth/login" }];
      }
      if (command === "bridge_call" && payload.command === "validate_login_request_contract") {
        throw new Error("ログイン設定の項目がOpenAPIのリクエスト定義にありません: password, username");
      }
      return {};
    });
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "http://vm.local";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("openapi-path").dispatchEvent(new window.Event("change"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.getElementById("auth-enabled").checked = true;
    document.getElementById("auth-login-op").value = "login";
    document.getElementById("auth-body").value = '{"username":"alice","password":"secret-value"}';
    document.getElementById("run-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("gen-error").textContent).toContain("password, username");
    expect(document.getElementById("gen-error").textContent).not.toContain("secret-value");
    expect(mockInvoke.mock.calls.some(([command]) => command === "write_config_file")).toBe(false);
    document.getElementById("auth-enabled").checked = false;
  });

  test.each(["unchanged", "changed", "no-event", "during-prepare"])("契約ケース準備後の設定変更を検査する: %s", async (mode) => {
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "http://vm.local/api";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("setup-sql-path").value = "";
    document.getElementById("teardown-sql-path").value = "";
    document.getElementById("pg-enabled").checked = false;
    document.getElementById("influx-enabled").checked = false;
    document.getElementById("auth-enabled").checked = false;
    document.getElementById("no-normal").checked = false;
    document.getElementById("no-abnormal").checked = false;
    document.getElementById("cookie-jar").checked = false;
    const master = {
      format: "api-tester.case-master", schemaVersion: 1,
      cases: [{ caseId: "TC-1", kind: "contract", title: "GET /users", reviewStatus: "draft", definition: {}, expected: {} }],
    };
    mockInvoke.mockImplementation(async (command, payload) => {
      if (["load_settings", "save_settings", "ensure_output_dir"].includes(command)) return {};
      if (command === "write_config_file") return "C:\\temp\\project.json";
      if (command === "bridge_call" && payload.command === "load_case_master") return master;
      if (command === "bridge_call" && payload.command === "save_case_master_reviews") {
        return {
          ...master,
          cases: master.cases.map((item) => ({
            ...item, reviewStatus: payload.args.updates[item.caseId] || item.reviewStatus,
          })),
        };
      }
      if (command === "run_script") return {};
      return {};
    });

    document.getElementById("run-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const prepareCall = mockInvoke.mock.calls.find(([command]) => command === "run_script");
    expect(prepareCall?.[1].args).toEqual(expect.arrayContaining([
      "prepare-contract", "--project", "C:\\temp\\project.json",
    ]));
    const prepareRunId = prepareCall[1].runId;
    emitTauriEvent("proc-line", {
      runId: prepareRunId,
      line: JSON.stringify({
        type: "artifact", kind: "case_master_json",
        path: "C:\\work\\results\\20260923-120000-deadbeef\\case-master.json",
      }),
    });
    if (mode === "during-prepare") document.getElementById("base-url").value = "http://changed-during-prepare.local";
    emitTauriEvent("proc-done", { runId: prepareRunId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    if (mode === "during-prepare") {
      expect(document.getElementById("execute-draft-button").hidden).toBe(true);
      expect(document.getElementById("case-review-message").textContent).toContain("作り直して");
      expect(mockInvoke.mock.calls.filter(([command]) => command === "run_script")).toHaveLength(1);
      return;
    }

    expect(document.getElementById("case-review-panel").hidden).toBe(false);
    expect(document.getElementById("execute-draft-button").hidden).toBe(false);
    expect(document.getElementById("execute-approved-button").hidden).toBe(true);
    expect(document.getElementById("run-status").textContent).toContain("準備");

    document.querySelector('[data-case-id="TC-1"] button').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-case-id="TC-1"] button').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.getElementById("execute-approved-button").hidden).toBe(false);
    if (mode !== "unchanged") {
      document.getElementById("base-url").value = "http://different.local/api";
      if (mode === "changed") document.getElementById("base-url").dispatchEvent(new window.Event("input"));
      document.getElementById("execute-approved-button").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(document.getElementById("execute-approved-button").hidden).toBe(true);
      expect(document.getElementById("case-review-message").textContent).toContain("作り直して");
      expect(mockInvoke.mock.calls.filter(([command]) => command === "run_script")).toHaveLength(1);
      return;
    }
    document.getElementById("execute-approved-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const runCalls = mockInvoke.mock.calls.filter(([command]) => command === "run_script");
    expect(runCalls[1][1].args).toEqual(expect.arrayContaining([
      "execute-contract", "--run-id", "20260923-120000-deadbeef",
    ]));
    expect(runCalls[1][1].args).not.toContain("--allow-draft");
    emitTauriEvent("proc-done", { runId: runCalls[1][1].runId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  test("最初の操作は実行設定と分離したケース準備だけを行う", async () => {
    const ids = ["openapi-path", "base-url", "output-dir", "setup-sql-path", "teardown-sql-path", "parallel"];
    for (const id of ids) document.getElementById(id).value = "";
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "http://vm.local/api";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("pg-enabled").checked = false;
    document.getElementById("influx-enabled").checked = false;
    document.getElementById("auth-enabled").checked = false;
    document.getElementById("dry-run").checked = true;
    document.getElementById("full-body").checked = true;
    document.getElementById("fail-fast").checked = true;
    document.getElementById("no-normal").checked = false;
    document.getElementById("no-abnormal").checked = false;
    document.getElementById("cookie-jar").checked = false;

    const master = {
      format: "api-tester.case-master", schemaVersion: 1,
      cases: [{ caseId: "TC-1", kind: "contract", title: "GET /users", reviewStatus: "draft", definition: {}, expected: {} }],
    };
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "load_settings" || command === "save_settings" || command === "ensure_output_dir") return {};
      if (command === "write_config_file") return "C:\\temp\\project.json";
      if (command === "bridge_call" && payload.command === "load_case_master") return master;
      if (command === "run_script") return {};
      return {};
    });

    document.getElementById("run-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const projectWrite = mockInvoke.mock.calls.find(([command]) => command === "write_config_file");
    expect(projectWrite?.[1].data).toEqual(expect.objectContaining({
      schemaVersion: 1,
      openapiPath: "C:\\work\\openapi.json",
      baseUrl: "http://vm.local/api",
      outputDir: "C:\\work\\results",
    }));
    expect(JSON.stringify(projectWrite?.[1].data)).not.toMatch(/password|token|cookie/i);

    const runCall = mockInvoke.mock.calls.find(([command]) => command === "run_script");
    expect(runCall?.[1]).toEqual(expect.objectContaining({
      script: "workflow/cli.py",
      args: expect.arrayContaining([
        "prepare-contract", "--project", "C:\\temp\\project.json",
      ]),
    }));
    expect(runCall?.[1].args).not.toContain("--dry-run");
    expect(runCall?.[1].args).not.toContain("--parallel");
    expect(runCall?.[1].args).not.toContain("src/cli.py");
    expect(runCall?.[1].args).not.toContain("runner/runner.py");

    const runId = runCall?.[1].runId;
    emitTauriEvent("proc-line", {
      runId,
      line: JSON.stringify({
        type: "artifact", kind: "case_master_json",
        path: "C:\\work\\results\\20260923-120000-deadbeef\\case-master.json",
      }),
    });
    emitTauriEvent("proc-done", { runId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("open-result-button").disabled).toBe(true);
    expect(document.getElementById("execute-draft-button").hidden).toBe(false);
    expect(document.getElementById("run-status").textContent).toContain("ケース準備完了");
  });
});

describe("統一ワークフローによるDBシナリオ試験", () => {
  test.each([false, true])("DBシナリオの準備後の設定変更=%s", async (changed) => {
    document.getElementById("dbscenario-error").scrollIntoView = vi.fn();
    document.getElementById("openapi-path").value = "C:\\work\\openapi.json";
    document.getElementById("base-url").value = "http://vm.local/api";
    document.getElementById("output-dir").value = "C:\\work\\results";
    document.getElementById("dbscenario-path").value = "C:\\work\\scenarios.yaml";
    document.getElementById("pg-enabled").checked = true;
    document.getElementById("pg-host").value = "127.0.0.1";
    document.getElementById("pg-port").value = "5432";
    document.getElementById("pg-dbname").value = "api_test";
    document.getElementById("pg-user").value = "tester";
    document.getElementById("pg-password").value = "secret";
    document.getElementById("auth-enabled").checked = false;
    document.getElementById("dbscenario-dry-run").checked = true;
    document.getElementById("dbscenario-cookie-jar").checked = true;

    const master = {
      format: "api-tester.case-master", schemaVersion: 1,
      cases: [{ caseId: "DB-readUser", kind: "db-scenario", title: "Read user", reviewStatus: "draft", definition: {}, expected: {} }],
    };
    let temporaryFileCount = 0;
    mockInvoke.mockImplementation(async (command, payload) => {
      if (command === "load_settings" || command === "save_settings" || command === "ensure_output_dir") return {};
      if (command === "bridge_call" && payload.command === "load_case_master") return master;
      if (command === "bridge_call" && payload.command === "save_case_master_reviews") {
        return {
          ...master,
          cases: master.cases.map((item) => ({
            ...item, reviewStatus: payload.args.updates[item.caseId] || item.reviewStatus,
          })),
        };
      }
      if (command === "write_config_file") {
        temporaryFileCount += 1;
        return `C:\\temp\\config-${temporaryFileCount}.json`;
      }
      if (command === "run_script") return {};
      return {};
    });

    document.getElementById("dbscenario-run-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const prepareCall = mockInvoke.mock.calls.find(([command]) => command === "run_script");
    expect(prepareCall?.[1]).toEqual(expect.objectContaining({
      script: "workflow/cli.py",
      args: expect.arrayContaining([
        "prepare-db-scenarios", "--project",
      ]),
    }));
    expect(prepareCall?.[1].args).not.toContain("--runtime-config");
    const preparedRunId = prepareCall?.[1].runId;
    emitTauriEvent("proc-line", {
      runId: preparedRunId,
      line: JSON.stringify({
        type: "artifact", kind: "case_master_json",
        path: "C:\\work\\results\\20260923-120000-deadbeef\\case-master.json",
      }),
    });
    emitTauriEvent("proc-done", { runId: preparedRunId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.getElementById("dbscenario-case-review-panel").hidden).toBe(false);
    expect(document.getElementById("dbscenario-execute-draft-button").hidden).toBe(false);

    document.querySelector('[data-case-id="DB-readUser"] button').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector('[data-case-id="DB-readUser"] button').click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.getElementById("dbscenario-execute-approved-button").hidden).toBe(false);
    if (changed) {
      document.getElementById("pg-dbname").value = "different_database";
      document.getElementById("dbscenario-execute-approved-button").click();
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(document.getElementById("dbscenario-execute-approved-button").hidden).toBe(true);
      expect(document.getElementById("dbscenario-case-review-message").textContent).toContain("作り直して");
      expect(mockInvoke.mock.calls.filter(([command]) => command === "run_script")).toHaveLength(1);
      return;
    }
    document.getElementById("dbscenario-execute-approved-button").click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const runCalls = mockInvoke.mock.calls.filter(([command]) => command === "run_script");
    const runCall = runCalls[1];
    expect(runCall?.[1]).toEqual(expect.objectContaining({
      script: "workflow/cli.py",
      args: expect.arrayContaining([
        "execute-db-scenarios", "--project", "C:\\temp\\config-3.json",
        "--run-id", "20260923-120000-deadbeef", "--runtime-config", "C:\\temp\\config-2.json",
        "--dry-run", "--cookie-jar",
      ]),
    }));
    expect(runCall?.[1].args).not.toContain("--allow-draft");

    emitTauriEvent("proc-line", {
      runId: runCall?.[1].runId,
      line: JSON.stringify({ type: "artifact", kind: "db_report_excel", path: "C:\\work\\results\\run\\db-scenario-result.xlsx" }),
    });
    emitTauriEvent("proc-done", { runId: runCall?.[1].runId, code: 0 });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(document.getElementById("dbscenario-open-result-button").disabled).toBe(false);
    expect(document.querySelector('#dbscenario-artifacts [data-artifact-kind="db_report_excel"]')).not.toBeNull();
    expect(document.getElementById("dbscenario-status").textContent).toContain("すべてのDB確認に成功");
  });
});

// ---------- runStatusMeaning ----------

describe("runStatusMeaning", () => {
  test("run stage code 2 means a response-time warning", () => {
    expect(runStatusMeaning(2, "run").text).toContain("応答時間超過");
  });

  test("code 130 reports cancellation", () => {
    expect(runStatusMeaning(130).text).toContain("キャンセルしました");
  });

  test("unknown code falls back to a generic message", () => {
    expect(runStatusMeaning(99).text).toBe("終了コード 99");
  });
});

test('レビュー保存中は別ケースの操作も止め、応答後に再開する', async () => {
  const master={cases:[1,2].map(id=>({caseId:`lock-${id}`,kind:'contract',title:`case ${id}`,definition:{},expected:{},reviewStatus:'draft'}))};
  let finish;
  mockInvoke.mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
  renderCaseMaster(master,'/tmp/reviews.json');
  const buttons=[...document.querySelectorAll('#case-review-list .case-review-card button')];
  buttons[0].click();buttons[1].click();
  expect(mockInvoke).toHaveBeenCalledTimes(1);expect(buttons.every(button=>button.disabled)).toBe(true);
  finish({...master,cases:master.cases.map((item,index)=>({...item,reviewStatus:index===0?'reviewed':'draft'}))});
  await new Promise(resolve=>setTimeout(resolve,0));
  expect([...document.querySelectorAll('#case-review-list .case-review-card button')].every(button=>!button.disabled)).toBe(true);
});


test("保存ボタンは接続先を保存し認証情報を含めない", async () => {
  document.getElementById("base-url").value = "http://localhost:8100";
  document.getElementById("pg-password").value = "private-db-password";
  document.getElementById("auth-body").value = '{"password":"private-login-password"}';
  document.getElementById("settings-save").click();
  await vi.waitFor(() => expect(document.getElementById("settings-status").textContent).toContain("保存しました"));
  const saved = mockInvoke.mock.calls.find(([command]) => command === "save_settings")[1].data;
  expect(saved.gen_base_url).toBe("http://localhost:8100");
  expect(JSON.stringify(saved)).not.toContain("private-");
});

test("未対応項目を優先表示し対応済み項目も確認できる", () => {
  renderCaseMaster({cases: [], coverage: [
    {operationId: "op", location: "body", field: "x", keyword: "type", status: "生成済み"},
    {operationId: "op", location: "body", field: "y", keyword: "contains", status: "未対応"},
  ]}, "/tmp/master.json");
  const rows = document.querySelectorAll(".coverage-review tr");
  expect(rows[1].hidden).toBe(true);
  expect(rows[2].hidden).toBe(false);
  document.querySelector('.coverage-review input[type="checkbox"]').click();
  expect(rows[1].hidden).toBe(false);
});

test("実行成功は全仕様の合格を意味せずキャンセルもロールバックを保証しない", () => {
  expect(runOutcomeAdvice(0)).toContain("未実行");
  expect(runOutcomeAdvice(2)).toContain("合格ではありません");
  expect(runOutcomeAdvice(130)).toContain("ロールバックを保証しません");
  expect(runOutcomeAdvice(3)).toContain("接続先");
});
