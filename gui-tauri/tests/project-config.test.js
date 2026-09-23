import { describe, expect, test } from "vitest";
import { buildProjectData } from "../src/project-config.js";

describe("project config", () => {
  test("uses only checked operations and never includes runtime secrets", () => {
    const project = buildProjectData({
      openapiPath: "C:/api/openapi.json",
      baseUrl: "http://vm.local/api",
      outputDir: "C:/api/results",
      operations: ["getUser", "createUser"],
      uncheckedOperations: ["createUser"],
      setupSqlPath: "C:/api/setup.sql",
      teardownSqlPath: "C:/api/teardown.sql",
      dbScenariosPath: "C:/api/scenarios.yaml",
    });

    expect(project).toEqual({
      schemaVersion: 1,
      name: "API試験",
      openapiPath: "C:/api/openapi.json",
      baseUrl: "http://vm.local/api",
      outputDir: "C:/api/results",
      selectedOperations: ["getUser"],
      setupSqlPath: "C:/api/setup.sql",
      teardownSqlPath: "C:/api/teardown.sql",
      dbScenariosPath: "C:/api/scenarios.yaml",
    });
    expect(JSON.stringify(project)).not.toMatch(/password|token|cookie/i);
  });
});
