import { test, expect } from "vitest";
import { addErrorDbScope, collectErrorDbScopes } from "../src/error-db-scopes.js";

test("DB比較範囲を複数設定して削除できる", () => {
  const container = document.createElement("div");
  const scope = { table: "t_data", columns: ["id", "value"], where: { site_id: 1 } };
  addErrorDbScope(container, scope);
  addErrorDbScope(container, { ...scope, table: "audit" });
  expect(collectErrorDbScopes(container)).toEqual([scope, { ...scope, table: "audit" }]);
  container.querySelector("button").click();
  expect(collectErrorDbScopes(container)).toHaveLength(1);
  container.querySelector('[data-key="where"]').value = "broken";
  expect(() => collectErrorDbScopes(container)).toThrow("DB行条件");
});
