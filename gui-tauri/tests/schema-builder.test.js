import { beforeEach, describe, expect, test } from "vitest";
import {
  builderNodeToSchema,
  createSchemaNode,
  renderSchemaBuilder,
  schemaToBuilderNode,
} from "../src/schema-builder.js";

describe("body schema builder model", () => {
  test("loads nested object, required flags, limits, and existing JSON Schema options", () => {
    const source = {
      type: "object",
      required: ["profile"],
      properties: {
        profile: {
          type: "object",
          required: ["email"],
          properties: {
            email: { type: "string", format: "email", minLength: 3, maxLength: 120 },
          },
        },
      },
    };

    const node = schemaToBuilderNode(source);

    expect(node.properties[0]).toMatchObject({ name: "profile", required: true, type: "object" });
    expect(node.properties[0].properties[0]).toMatchObject({
      name: "email", required: true, type: "string", min: 3, max: 120,
      extra: { format: "email" },
    });
    expect(builderNodeToSchema(node)).toEqual(source);
  });

  test("preserves nullable JSON Schema types that the form does not narrow", () => {
    const source = { type: ["string", "null"], minLength: 2 };
    expect(builderNodeToSchema(schemaToBuilderNode(source))).toEqual(source);
  });

  test("builds request properties and an array of nested objects", () => {
    const node = createSchemaNode("object");
    node.properties = [
      {
        ...createSchemaNode("string", "email", true),
        min: "4",
        max: "100",
        extra: { format: "email" },
      },
      {
        ...createSchemaNode("array", "items"),
        min: "1",
        max: "5",
        items: {
          ...createSchemaNode("object"),
          properties: [
            { ...createSchemaNode("integer", "quantity", true), min: "1", max: "20" },
          ],
        },
      },
    ];

    expect(builderNodeToSchema(node)).toEqual({
      type: "object",
      required: ["email"],
      properties: {
        email: { type: "string", format: "email", minLength: 4, maxLength: 100 },
        items: {
          type: "array",
          minItems: 1,
          maxItems: 5,
          items: {
            type: "object",
            required: ["quantity"],
            properties: { quantity: { type: "integer", minimum: 1, maximum: 20 } },
          },
        },
      },
    });
  });

  test("rejects empty or duplicate field names and invalid limits", () => {
    const node = createSchemaNode("object");
    node.properties = [createSchemaNode("string")];
    expect(() => builderNodeToSchema(node)).toThrow("項目名を入力してください");

    node.properties[0].name = "id";
    node.properties.push(createSchemaNode("integer", "id"));
    expect(() => builderNodeToSchema(node)).toThrow("重複しています");

    node.properties = [{ ...createSchemaNode("string", "name"), min: "8", max: "2" }];
    expect(() => builderNodeToSchema(node)).toThrow("最小文字数は最大文字数以下");
  });
});

describe("body schema builder UI", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="builder"></div>';
  });

  test("creates nested object fields and serializes the selected type and constraints", () => {
    const container = document.getElementById("builder");
    let model = null;
    const update = (next) => { model = next; };
    renderSchemaBuilder(container, model, update);

    container.querySelector('[data-role="create-schema"]').click();
    container.querySelector('[data-role="add-property"]').click();
    let properties = container.querySelectorAll(".schema-node-property");
    properties[0].querySelector('[data-role="property-name"]').value = "profile";
    properties[0].querySelector('[data-role="property-name"]').dispatchEvent(new window.Event("input", { bubbles: true }));
    properties[0].querySelector('[data-role="property-required"]').click();
    properties[0].querySelector('[data-role="schema-type"]').value = "object";
    properties[0].querySelector('[data-role="schema-type"]').dispatchEvent(new window.Event("change", { bubbles: true }));

    container.querySelector(".schema-node-property").querySelector('[data-role="add-property"]').click();
    properties = container.querySelectorAll(".schema-node-property");
    const age = properties[1];
    age.querySelector('[data-role="property-name"]').value = "age";
    age.querySelector('[data-role="property-name"]').dispatchEvent(new window.Event("input", { bubbles: true }));
    age.querySelector('[data-role="property-required"]').click();
    age.querySelector('[data-role="schema-type"]').value = "integer";
    age.querySelector('[data-role="schema-type"]').dispatchEvent(new window.Event("change", { bubbles: true }));
    const updatedAge = container.querySelectorAll(".schema-node-property")[1];
    updatedAge.querySelector('[data-role="constraint-min"]').value = "0";
    updatedAge.querySelector('[data-role="constraint-min"]').dispatchEvent(new window.Event("input", { bubbles: true }));

    expect(builderNodeToSchema(model)).toEqual({
      type: "object",
      required: ["profile"],
      properties: {
        profile: {
          type: "object",
          required: ["age"],
          properties: { age: { type: "integer", minimum: 0 } },
        },
      },
    });
  });
});

test("正常系入力は文字列・数値・false・空文字を区別して保存し解除できる", () => {
  const node = schemaToBuilderNode({ type: "object", properties: {
    username: { type: "string" }, password: { type: "string" }, enabled: { type: "boolean" }, count: { type: "integer" },
  } });
  const host = document.createElement("div");
  renderSchemaBuilder(host, node, () => {}, { requestExamples: true });
  const cards = host.querySelectorAll('.schema-node-property');
  ["real-user", "", "false", "12"].forEach((value, i) => {
    const toggle = cards[i].querySelector('[data-role="example-enabled"]');
    toggle.click();
    const input = cards[i].querySelector('[data-role="example-value"]');
    input.value = value;
    input.dispatchEvent(new window.Event("input"));
  });
  expect(cards[1].querySelector('[data-role="example-value"]').type).toBe("password");
  const schema = builderNodeToSchema(node);
  expect(schema.properties.username.example).toBe("real-user");
  expect(schema.properties.password.example).toBe("");
  expect(schema.properties.enabled.example).toBe(false);
  expect(schema.properties.count.example).toBe(12);
  expect(builderNodeToSchema(schemaToBuilderNode(schema))).toEqual(schema);
  const disable = cards[0].querySelector('[data-role="example-enabled"]');
  disable.checked = false;
  disable.dispatchEvent(new window.Event("change"));
  expect(builderNodeToSchema(node).properties.username).not.toHaveProperty("example");
  node.properties[3].exampleText = "1.5";
  expect(() => builderNodeToSchema(node)).toThrow("データ型");
});
