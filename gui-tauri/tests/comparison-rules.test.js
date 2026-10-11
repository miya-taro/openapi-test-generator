import { expect, test } from "vitest";
import { applyComparisonRules, comparisonRulesFromSchema, renderComparisonRules, validateComparisonBody } from "../src/comparison-rules.js";

const schema = () => ({ type: "object", properties: {
  start: { type: "string", format: "date-time" }, end: { type: "string", format: "date-time" },
} });
const rules = () => [{ fields: ["start", "end"], operator: "<=", lower: "2026-01-01T00:00:00Z", upper: "2026-01-02T00:00:00Z" }];

test("日時の条件を保存・読込し、タイムゾーンと細かい秒を比較する", () => {
  const saved = applyComparisonRules(schema(), rules());
  expect(comparisonRulesFromSchema(saved)).toEqual(rules());
  expect(() => validateComparisonBody({ start: "2026-01-01T09:00:00.1234567+09:00", end: "2026-01-01T00:00:00.123456700Z" }, saved)).not.toThrow();
  expect(() => validateComparisonBody({ start: "2026-01-01T00:00:00.1234568Z", end: "2026-01-01T00:00:00.1234567Z" }, saved)).toThrow("start <= end");
  expect(() => validateComparisonBody({}, saved)).not.toThrow();
  expect(applyComparisonRules(saved, [])["x-otg-comparison-rules"]).toBeUndefined();
});

test("矛盾した値と重複項目を拒否する", () => {
  expect(() => applyComparisonRules(schema(), [{ ...rules()[0], upper: rules()[0].lower }])).toThrow("小さい試験値");
  expect(() => applyComparisonRules(schema(), [...rules(), ...rules()])).toThrow("重複");
  expect(() => applyComparisonRules(schema(), [{ ...rules()[0], lower: 1 }])).toThrow("date-time");
});

test("画面の大小条件・試験値の編集と削除が保存対象に反映される", () => {
  const container = document.createElement("div"), model = rules();
  renderComparisonRules(container, model, { properties: [{ name: "start" }, { name: "end" }] });
  const select = container.querySelectorAll("select")[1];
  select.value = "<"; select.dispatchEvent(new window.Event("change"));
  const input = container.querySelector("input");
  input.value = '"2025-01-01T00:00:00Z"'; input.dispatchEvent(new window.Event("input"));
  expect(applyComparisonRules(schema(), model)["x-otg-comparison-rules"][0]).toMatchObject({ operator: "<", lower: "2025-01-01T00:00:00Z" });
  container.querySelector("button").click(); expect(model).toEqual([]);
});
