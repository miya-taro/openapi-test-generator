const SCHEMA_TYPES = ["object", "string", "integer", "number", "boolean", "array", "null"];
const CONSTRAINT_KEYS = [
  "minLength", "maxLength", "minimum", "maximum",
  "minItems", "maxItems", "minProperties", "maxProperties",
];

const CONSTRAINTS_BY_TYPE = {
  string: [
    { key: "min", schemaKey: "minLength", label: "最小文字数", integer: true },
    { key: "max", schemaKey: "maxLength", label: "最大文字数", integer: true },
  ],
  integer: [
    { key: "min", schemaKey: "minimum", label: "最小値" },
    { key: "max", schemaKey: "maximum", label: "最大値" },
  ],
  number: [
    { key: "min", schemaKey: "minimum", label: "最小値" },
    { key: "max", schemaKey: "maximum", label: "最大値" },
  ],
  array: [
    { key: "min", schemaKey: "minItems", label: "最小件数", integer: true },
    { key: "max", schemaKey: "maxItems", label: "最大件数", integer: true },
  ],
  object: [
    { key: "min", schemaKey: "minProperties", label: "最小項目数", integer: true },
    { key: "max", schemaKey: "maxProperties", label: "最大項目数", integer: true },
  ],
};

const TYPE_LABELS = {
  object: "object（オブジェクト）",
  string: "string（文字列）",
  integer: "integer（整数）",
  number: "number（数値）",
  boolean: "boolean（真偽値）",
  array: "array（配列）",
  null: "null（null値）",
};

export function createSchemaNode(type = "object", name = "", required = false) {
  return {
    name,
    required,
    type: SCHEMA_TYPES.includes(type) ? type : "object",
    originalType: undefined,
    typeChanged: false,
    min: "",
    max: "",
    properties: [],
    extraRequired: [],
    items: type === "array" ? createSchemaNode("object") : null,
    extra: {},
  };
}

export function schemaToBuilderNode(schema, name = "", required = false) {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    return createSchemaNode("object", name, required);
  }

  const schemaTypes = Array.isArray(schema.type) ? schema.type : [schema.type];
  const inferredType = schemaTypes.find((type) => SCHEMA_TYPES.includes(type) && type !== "null")
    || schemaTypes.find((type) => SCHEMA_TYPES.includes(type))
    || (schema.items !== undefined ? "array" : schema.properties !== undefined ? "object" : "object");
  const node = createSchemaNode(inferredType, name, required);
  node.originalType = schema.type;
  node.extra = { ...schema };
  delete node.extra.type;
  delete node.extra.properties;
  delete node.extra.required;
  delete node.extra.items;
  for (const key of CONSTRAINT_KEYS) delete node.extra[key];

  const constraints = CONSTRAINTS_BY_TYPE[inferredType] || [];
  node.min = schema[constraints.find((constraint) => constraint.key === "min")?.schemaKey] ?? "";
  node.max = schema[constraints.find((constraint) => constraint.key === "max")?.schemaKey] ?? "";

  if (inferredType === "object" && schema.properties && typeof schema.properties === "object") {
    const requiredProperties = new Set(Array.isArray(schema.required) ? schema.required : []);
    node.properties = Object.entries(schema.properties).map(([propertyName, propertySchema]) =>
      schemaToBuilderNode(propertySchema, propertyName, requiredProperties.has(propertyName)),
    );
    node.extraRequired = [...requiredProperties].filter((propertyName) => !Object.hasOwn(schema.properties, propertyName));
  } else if (Array.isArray(schema.required)) {
    node.extraRequired = [...schema.required];
  }
  if (inferredType === "array" && schema.items && typeof schema.items === "object") {
    node.items = schemaToBuilderNode(schema.items);
  } else if (inferredType === "array") {
    node.items = null;
  }
  return node;
}

export function builderNodeToSchema(node) {
  if (!node || !SCHEMA_TYPES.includes(node.type)) {
    throw new Error("body全体または項目のデータ型を選択してください");
  }

  const schema = { ...(node.extra || {}) };
  schema.type = node.typeChanged || node.originalType === undefined ? node.type : node.originalType;
  const constraints = CONSTRAINTS_BY_TYPE[node.type] || [];
  for (const constraint of constraints) {
    const rawValue = node[constraint.key];
    if (rawValue === "" || rawValue === null || rawValue === undefined) continue;
    const value = Number(rawValue);
    if (!Number.isFinite(value) || (constraint.integer && !Number.isInteger(value)) || value < 0 && constraint.integer) {
      throw new Error(`${constraint.label}には${constraint.integer ? "0以上の整数" : "数値"}を指定してください`);
    }
    schema[constraint.schemaKey] = value;
  }

  const minConstraint = constraints.find((constraint) => constraint.key === "min");
  const maxConstraint = constraints.find((constraint) => constraint.key === "max");
  if (
    minConstraint && maxConstraint &&
    schema[minConstraint.schemaKey] !== undefined &&
    schema[maxConstraint.schemaKey] !== undefined &&
    schema[minConstraint.schemaKey] > schema[maxConstraint.schemaKey]
  ) {
    throw new Error(`${minConstraint.label}は${maxConstraint.label}以下にしてください`);
  }

  if (node.type === "object") {
    const properties = {};
    const required = [...(node.extraRequired || [])];
    for (const child of node.properties || []) {
      const name = String(child.name || "").trim();
      if (!name) throw new Error("項目名を入力してください");
      if (Object.prototype.hasOwnProperty.call(properties, name)) {
        throw new Error(`項目名「${name}」が重複しています`);
      }
      properties[name] = builderNodeToSchema(child);
      if (child.required) required.push(name);
    }
    if (Object.keys(properties).length) schema.properties = properties;
    else delete schema.properties;
    if (required.length) schema.required = [...new Set(required)];
    else delete schema.required;
  }

  if (node.type === "array") {
    if (node.items) schema.items = builderNodeToSchema(node.items);
    else delete schema.items;
  }
  return schema;
}

function makeElement(tag, className, text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function makeTypeSelect(node, onTypeChange) {
  const select = document.createElement("select");
  select.dataset.role = "schema-type";
  select.setAttribute("aria-label", "データ型");
  for (const type of SCHEMA_TYPES) {
    const option = makeElement("option", "", TYPE_LABELS[type]);
    option.value = type;
    select.appendChild(option);
  }
  select.value = node.type;
  select.addEventListener("change", () => onTypeChange(select.value));
  return select;
}

function makeConstraintInput(node, constraint, onChange) {
  const field = makeElement("label", "schema-constraint");
  field.appendChild(makeElement("span", "", constraint.label));
  const input = document.createElement("input");
  input.type = "number";
  input.dataset.role = `constraint-${constraint.key}`;
  input.setAttribute("aria-label", constraint.label);
  input.value = node[constraint.key] ?? "";
  input.step = constraint.integer ? "1" : "any";
  if (constraint.integer) input.min = "0";
  input.addEventListener("input", () => onChange(input.value));
  field.appendChild(input);
  return field;
}

function renderNode(node, context, refresh, notify) {
  const card = makeElement("section", `schema-node schema-node-${context.kind}`);
  if (context.depth > 0) card.classList.add("schema-node-nested");

  if (context.kind === "property") {
    const heading = makeElement("div", "schema-node-heading");
    const name = document.createElement("input");
    name.type = "text";
    name.dataset.role = "property-name";
    name.placeholder = "項目名（例: email）";
    name.setAttribute("aria-label", "項目名");
    name.value = node.name || "";
    name.addEventListener("input", () => {
      node.name = name.value;
      notify();
    });
    heading.appendChild(name);

    const requiredLabel = makeElement("label", "schema-required");
    const required = document.createElement("input");
    required.type = "checkbox";
    required.dataset.role = "property-required";
    required.checked = !!node.required;
    required.addEventListener("change", () => {
      node.required = required.checked;
      notify();
    });
    requiredLabel.append(required, document.createTextNode("必須"));
    heading.appendChild(requiredLabel);

    const remove = makeElement("button", "secondary schema-remove", "削除");
    remove.type = "button";
    remove.addEventListener("click", context.onRemove);
    heading.appendChild(remove);
    card.appendChild(heading);
  } else if (context.kind === "item") {
    card.appendChild(makeElement("div", "schema-item-title", context.title || "配列の要素"));
  } else if (context.kind === "root") {
    card.appendChild(makeElement("div", "schema-root-title", context.title || "body全体の型"));
  }

  const typeField = makeElement("label", "schema-type-field");
  typeField.appendChild(makeElement("span", "", "データ型"));
  typeField.appendChild(makeTypeSelect(node, (type) => {
    node.type = type;
    node.typeChanged = true;
    node.min = "";
    node.max = "";
    if (type === "array" && !node.items) node.items = createSchemaNode("object");
    notify();
    refresh();
  }));
  card.appendChild(typeField);

  const constraints = CONSTRAINTS_BY_TYPE[node.type] || [];
  if (constraints.length) {
    const limits = makeElement("div", "schema-constraints");
    for (const constraint of constraints) {
      limits.appendChild(makeConstraintInput(node, constraint, (value) => {
        node[constraint.key] = value;
        notify();
      }));
    }
    card.appendChild(limits);
  }

  if (node.type === "object") {
    const properties = makeElement("div", "schema-properties");
    properties.appendChild(makeElement("div", "schema-subheading", "中の項目"));
    for (const [index, child] of (node.properties || []).entries()) {
      properties.appendChild(renderNode(child, {
        kind: "property",
        depth: context.depth + 1,
        onRemove: () => {
          node.properties.splice(index, 1);
          notify();
          refresh();
        },
      }, refresh, notify));
    }
    const add = makeElement("button", "secondary schema-add", "＋ 項目を追加");
    add.type = "button";
    add.dataset.role = "add-property";
    add.addEventListener("click", () => {
      node.properties ||= [];
      node.properties.push(createSchemaNode("string"));
      notify();
      refresh();
    });
    properties.appendChild(add);
    card.appendChild(properties);
  }

  if (node.type === "array") {
    const items = makeElement("div", "schema-array-items");
    items.appendChild(makeElement("div", "schema-subheading", "配列の要素"));
    if (node.items) {
      items.appendChild(renderNode(node.items, {
        kind: "item",
        depth: context.depth + 1,
        title: "要素のデータ型と制約",
      }, refresh, notify));
      const removeItems = makeElement("button", "secondary schema-remove-items", "要素定義を外す");
      removeItems.type = "button";
      removeItems.addEventListener("click", () => {
        node.items = null;
        notify();
        refresh();
      });
      items.appendChild(removeItems);
    } else {
      const addItems = makeElement("button", "secondary schema-add-items", "要素の型を設定");
      addItems.type = "button";
      addItems.addEventListener("click", () => {
        node.items = createSchemaNode("object");
        notify();
        refresh();
      });
      items.appendChild(addItems);
    }
    card.appendChild(items);
  }

  return card;
}

export function renderSchemaBuilder(container, node, onChange = () => {}) {
  const render = () => {
    container.replaceChildren();
    if (!node) {
      container.appendChild(makeElement("p", "field-caption schema-empty", "schema未設定です。必要な場合は作成してください。"));
      const addSchema = makeElement("button", "secondary schema-create", "＋ body schemaを作成");
      addSchema.type = "button";
      addSchema.dataset.role = "create-schema";
      addSchema.addEventListener("click", () => {
        node = createSchemaNode("object");
        onChange(node);
        render();
      });
      container.appendChild(addSchema);
      return;
    }

    const refresh = () => render();
    const notify = () => onChange(node);
    container.appendChild(renderNode(node, { kind: "root", depth: 0 }, refresh, notify));
  };
  render();
}
