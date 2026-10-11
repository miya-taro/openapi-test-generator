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

test("InfluxDB比較範囲の種類と固定期間を保存し、PostgreSQLに戻せる", () => {
  const container = document.createElement("div");
  const scope = { engine: "influxdb", table: "measure", columns: ["time", "item", "value"], where: { item: "a" }, time_start: "2026-01-01T00:00:00Z", time_end: "2026-01-02T00:00:00Z" };
  addErrorDbScope(container, scope);
  expect(collectErrorDbScopes(container)).toEqual([scope]);
  expect(container.querySelector('[data-key="time_start"]').parentElement.hidden).toBe(false);
  const engine = container.querySelector('[data-key="engine"]');
  engine.value = "postgres"; engine.dispatchEvent(new window.Event("change"));
  expect(container.querySelector('[data-key="time_start"]').parentElement.hidden).toBe(true);
  expect(collectErrorDbScopes(container)[0]).not.toHaveProperty("time_start");
});
