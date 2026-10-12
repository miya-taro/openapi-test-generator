import { templateControls } from "./scenario-templates.js";
import { buildSqlResponseScenario, initSqlResponseEditor } from "./sql-response-editor.js";
import { buildInsertScenario, initInsertEditor } from "./insert-editor.js";
import { validateComparisonBody } from "./comparison-rules.js";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const SEEDED_METHODS = new Set(["PUT", "PATCH", "DELETE"]);

function byId(id) {
  return document.getElementById(id);
}

function make(tag, className, text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function valueAtPath(value, path) {
  if (String(path || "").trim() === "$") return value;
  return String(path || "").replace(/\[\]/g, ".0").split(".").filter(Boolean).reduce((node, key) => {
    if (node === undefined || node === null) return undefined;
    return node[key];
  }, value);
}

function parseJson(text, label, requireObject = true) {
  try {
    const value = JSON.parse(text);
    if (requireObject && (!value || typeof value !== "object" || Array.isArray(value))) {
      throw new Error("JSONオブジェクトを入力してください");
    }
    return value;
  } catch (error) {
    throw new Error(`${label}のJSONを確認してください: ${error.message}`, { cause: error });
  }
}

function parseScalar(text, label) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) throw new Error(`${label}を入力してください`);
  try {
    return JSON.parse(trimmed);
  } catch {
    return trimmed;
  }
}

function validateBodyValue(value, schema, label) {
  const type = schemaType(schema);
  const validType = type === "integer" ? Number.isInteger(value)
    : type === "number" ? typeof value === "number" && Number.isFinite(value)
      : type === "string" ? typeof value === "string"
        : type === "array" ? Array.isArray(value)
          : type === "boolean" ? typeof value === "boolean"
            : type === "object" ? value !== null && typeof value === "object" && !Array.isArray(value)
              : true;
  if (!validType) throw new Error(`${label}は${type}型の値を入力してください`);
  if (schema?.format === "date-time" && !isDateTime(value)) {
    throw new Error(`${label}はタイムゾーンを含む日時で入力してください`);
  }
  if (type === "array" && schema?.items) {
    value.forEach((item, index) => validateBodyValue(item, schema.items, `${label}[${index}]`));
  }
}

function isDateTime(value) {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?([Zz]|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return false;
  const [, y, m, d, h, minute, second, zone] = match;
  const year = Number(y);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year > 0 && Number(m) >= 1 && Number(m) <= 12 && Number(d) >= 1 && Number(d) <= days[Number(m) - 1]
    && Number(h) <= 23 && Number(minute) <= 59 && Number(second) <= 59
    && (zone.toLowerCase() === "z" || (Number(zone.slice(1, 3)) <= 23 && Number(zone.slice(4)) <= 59));
}

function sampleValue(schema = {}, propertyName = "value", depth = 0) {
  if (depth > 8) return {};
  if (Object.hasOwn(schema, "example")) return schema.example;
  if (Object.hasOwn(schema, "default")) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0];
  let type = Array.isArray(schema.type) ? schema.type.find((item) => item !== "null") : schema.type;
  if (type === "integer" || type === "number") return schema.minimum ?? 1;
  if (type === "boolean") return false;
  if (type === "array") {
    const minItems = schema.maxItems === 0 ? 0 : Math.max(1, Number(schema.minItems) || 0);
    return Array.from({ length: Math.min(minItems, 3) }, () => sampleValue(schema.items || {}, "item", depth + 1));
  }
  if (type === "object" || schema.properties) {
    const required = new Set(schema.required || Object.keys(schema.properties || {}));
    return Object.fromEntries(Object.entries(schema.properties || {})
      .filter(([key]) => required.has(key))
      .map(([key, child]) => [key, sampleValue(child, key, depth + 1)]));
  }
  if (schema.format === "email") return "test@example.com";
  if (schema.format === "date-time") return "2026-01-01T00:00:00Z";
  if (schema.format === "date") return "2026-01-01";
  return propertyName;
}

function schemaFields(schema, prefix = "", depth = 0, direction = "request", parentRequired = true) {
  if (!schema || typeof schema !== "object" || depth > 12) return [];
  const type = schemaType(schema);
  if (type === "array") {
    if (!prefix && direction === "request") {
      return [{ path: "$", type: "array", required: parentRequired, schema }];
    }
    return prefix
      ? [{ path: prefix, type: "array", required: parentRequired, schema }]
      : schemaFields(schema.items || {}, "", depth + 1, direction, parentRequired);
  }
  const properties = schema.properties && typeof schema.properties === "object" ? schema.properties : {};
  if (type === "object" || Object.keys(properties).length) {
    const entries = Object.entries(properties);
    if (!entries.length) {
      if (prefix) return [{ path: prefix, type: "object", required: parentRequired, schema }];
      return direction === "request" && type === "object"
        ? [{ path: "$", type: "object", required: parentRequired, schema }]
        : [];
    }
    const required = new Set(schema.required || []);
    return entries.flatMap(([name, child]) => {
      if (direction === "request" && child?.readOnly) return [];
      if (direction === "response" && child?.writeOnly) return [];
      const path = prefix ? `${prefix}.${name}` : name;
      return schemaFields(child, path, depth + 1, direction, parentRequired && required.has(name));
    });
  }
  const path = prefix || (direction === "request" && (type || schema.format) ? "$" : "");
  return path ? [{ path, type: type || schema.format || "value", required: parentRequired, schema }] : [];
}

function schemaFieldLabel(field) {
  return `${field.path}（${field.type}${field.required ? "・必須" : ""}）`;
}

function schemaAtPath(schema, path) {
  const normalizedPath = String(path || "$").trim();
  if (!normalizedPath || normalizedPath === "$") return schema;
  let current = schema;
  for (const part of normalizedPath.split(".").filter(Boolean)) {
    if (schemaType(current) === "array") current = current.items;
    current = current?.properties?.[part];
    if (!current) return null;
  }
  return current;
}

function schemaType(schema) {
  const declared = Array.isArray(schema?.type)
    ? schema.type.find((item) => item !== "null")
    : schema?.type;
  if (declared) return declared;
  if (schema?.properties || Object.hasOwn(schema || {}, "additionalProperties")) return "object";
  if (schema?.items) return "array";
  return undefined;
}

function requireDbIdentifier(value, label) {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(value || ""))) {
    throw new Error(`${label}は英字または_で始まる英数字・_で入力してください`);
  }
  return value;
}

function schemaConstraintSummary(schema = {}) {
  const constraints = [];
  if (schema.format) constraints.push(`形式: ${schema.format}`);
  if (schema.minLength !== undefined) constraints.push(`最小${schema.minLength}文字`);
  if (schema.maxLength !== undefined) constraints.push(`最大${schema.maxLength}文字`);
  if (schema.minimum !== undefined) constraints.push(`最小${schema.minimum}`);
  if (schema.maximum !== undefined) constraints.push(`最大${schema.maximum}`);
  if (schema.minItems !== undefined) constraints.push(`最小${schema.minItems}件`);
  if (schema.maxItems !== undefined) constraints.push(`最大${schema.maxItems}件`);
  if (Array.isArray(schema.enum) && schema.enum.length) constraints.push(`候補: ${schema.enum.join(" / ")}`);
  return constraints.join("・");
}

function addRequestValueEditor(cell, field, initialValue) {
  const schema = field.schema || {};
  const type = schemaType(schema) || field.type;
  const initial = initialValue === undefined ? sampleValue(schema, field.path) : initialValue;
  const editor = type === "array" || type === "object" || type === "value"
    ? make("textarea")
    : Array.isArray(schema.enum) && schema.enum.length
      ? make("select")
      : type === "boolean"
        ? make("select")
        : make("input");

  if (editor.tagName === "TEXTAREA") {
    editor.rows = 3;
    editor.value = JSON.stringify(initial ?? (type === "array" ? [] : {}), null, 2);
    editor.setAttribute("aria-label", `${field.path}のAPI送信値（JSON）`);
  } else if (editor.tagName === "SELECT") {
    const choices = Array.isArray(schema.enum) && schema.enum.length
      ? schema.enum
      : [true, false];
    for (const choice of choices) {
      const option = make("option", "", String(choice));
      option.value = JSON.stringify(choice);
      editor.append(option);
    }
    editor.value = JSON.stringify(initial ?? choices[0]);
    editor.setAttribute("aria-label", `${field.path}のAPI送信値`);
  } else {
    editor.type = type === "integer" || type === "number" ? "number" : "text";
    if (type === "integer") editor.step = "1";
    if (type === "number") editor.step = "any";
    for (const [key, attribute] of [["minimum", "min"], ["maximum", "max"], ["minLength", "minLength"], ["maxLength", "maxLength"]]) {
      if (schema[key] !== undefined) editor.setAttribute(attribute, String(schema[key]));
    }
    editor.value = initial === undefined || initial === null ? "" : String(initial);
    editor.setAttribute("aria-label", `${field.path}のAPI送信値`);
  }
  editor.dataset.apiValue = "true";

  if (!field.required) {
    const include = make("input");
    include.type = "checkbox";
    include.dataset.includeField = "true";
    include.checked = initialValue !== undefined;
    include.setAttribute("aria-label", `${field.path}を送る`);
    include.addEventListener("change", () => {
      editor.disabled = !include.checked;
    });
    editor.disabled = !include.checked;
    const optionalToggle = make("label", "db-scenario-optional-value");
    optionalToggle.append(include, make("span", "", "送る"));
    cell.append(optionalToggle);
  }
  cell.append(editor);
  const summary = schemaConstraintSummary(schema);
  if (summary) cell.append(make("small", "db-scenario-constraint", summary));
}

function addWriteMappingRow(container, field, initialValue) {
  const row = make("tr", "db-scenario-map-row");
  const sourceCell = make("td");
  row.dataset.fieldPath = field.path;
  row.dataset.required = String(field.required);
  row.requestSchema = field.schema || {};
  const source = make("span", "db-scenario-api-field", schemaFieldLabel(field));
  sourceCell.append(source);
  row.append(sourceCell);

  const requestValueCell = make("td", "db-scenario-request-value-cell");
  addRequestValueEditor(requestValueCell, field, initialValue);
  row.append(requestValueCell);

  const targetCell = make("td");
  const target = make("input");
  target.type = "text";
  target.placeholder = "例: email";
  target.value = "";
  target.setAttribute("aria-label", "DBカラム");
  targetCell.append(target);
  row.append(targetCell);

  const transformCell = make("td");
  const transform = make("select");
  for (const [value, label] of [["direct", "同じ値"], ["lower", "小文字にする"], ["upper", "大文字にする"], ["fixed", "固定値"]]) {
    const option = make("option", "", label);
    option.value = value;
    transform.append(option);
  }
  transform.value = "direct";
  transform.setAttribute("aria-label", "値の変換");
  transformCell.append(transform);
  row.append(transformCell);

  const fixedCell = make("td");
  const fixedValue = make("input");
  fixedValue.type = "text";
  fixedValue.placeholder = 'JSON値: "member" / 1 / true';
  fixedValue.value = "";
  fixedValue.setAttribute("aria-label", "固定値");
  fixedCell.append(fixedValue);
  row.append(fixedCell);

  const whereCell = make("td", "db-scenario-map-check-cell");
  const where = make("input");
  where.type = "checkbox";
  where.checked = false;
  where.setAttribute("aria-label", "保存後の照合に使う");
  whereCell.append(where);
  row.append(whereCell);

  container.append(row);
}

function addReadMappingRow(container, field) {
  const row = make("tr", "db-scenario-map-row");
  row.dataset.responsePath = field.path;
  row.append(make("td", "db-scenario-api-field", schemaFieldLabel(field)));
  const columnCell = make("td");
  const column = make("input");
  column.type = "text";
  column.placeholder = "DBカラムを入力";
  column.setAttribute("aria-label", `${field.path}に対応するDBカラム`);
  column.dataset.dbColumn = "true";
  columnCell.append(column);
  row.append(columnCell);
  container.append(row);
}

function addReadFilterRow(container, parameter) {
  const row = make("tr", "db-scenario-map-row");
  row.dataset.parameterSource = parameter.source;
  row.dataset.parameterName = parameter.name;
  row.dataset.parameterFormat = parameter.format || "";
  const sourceCell = make("td");
  const required = parameter.required ? "・必須" : "";
  const location = { query: "Query", path: "Path", body: "Body" }[parameter.source];
  sourceCell.append(make("span", "db-scenario-api-field", `${parameter.name}（${location}${required}）`));
  row.append(sourceCell);

  const valueCell = make("td");
  if (parameter.source === "body") {
    const value = make("input");
    value.type = "text";
    value.dataset.requestValue = "true";
    value.placeholder = 'JSON値: 1 / "A" / ["x"]';
    value.value = parameter.defaultValue === undefined ? "" : JSON.stringify(parameter.defaultValue);
    value.setAttribute("aria-label", `${parameter.name}の送信値`);
    valueCell.append(value);
  } else {
    valueCell.append(make("span", "field-caption", "DBから選択"));
  }
  row.append(valueCell);

  const columnCell = make("td");
  const column = make("input");
  column.type = "text";
  column.placeholder = "例: created_at";
  column.value = "";
  column.setAttribute("aria-label", "検索に使うDBカラム");
  column.dataset.dbColumn = "true";
  column.addEventListener("change", syncMappedQueryParams);
  columnCell.append(column);
  row.append(columnCell);

  const operatorCell = make("td");
  const operator = make("select");
  for (const [value, label] of [["=", "と等しい"], [">=", "以上"], [">", "より大きい"], ["<=", "以下"], ["<", "より小さい"], ["in", "配列に含まれる"]]) {
    const option = make("option", "", label);
    option.value = value;
    operator.append(option);
  }
  const operatorPrompt = make("option", "", "比較方法を選択");
  operatorPrompt.value = "";
  operator.prepend(operatorPrompt);
  operator.value = "";
  operator.setAttribute("aria-label", "DBとの比較条件");
  operatorCell.append(operator);
  row.append(operatorCell);

  const groupCell = make("td");
  const group = make("select");
  for (const [value, label] of [["", "AND"], ["A", "OR A"], ["B", "OR B"]]) {
    const option = make("option", "", label);
    option.value = value;
    group.append(option);
  }
  group.setAttribute("aria-label", `${parameter.name}のORグループ`);
  group.dataset.orGroup = "true";
  groupCell.append(group);
  row.append(groupCell);

  const lookupCell = make("td");
  const label = make("label", "checkbox-label");
  const toggle = make("input"); toggle.type = "checkbox"; toggle.dataset.lookupEnabled = "true";
  toggle.setAttribute("aria-label", `${parameter.name}を別DBで参照`);
  label.append(toggle, document.createTextNode("別DBを参照して比較"));
  const fields = make("div", "db-lookup-fields"); fields.hidden = true;
  const controls = {};
  const add = (key, title, options) => {
    const holder = make("label", "form-field", title);
    const input = make(options ? "select" : "input");
    if (!options) input.type = "text";
    input.dataset.lookupField = key;
    input.setAttribute("aria-label", `${parameter.name}の${title}`);
    if (options) for (const [value, text] of options) {
      const option = make("option", "", text); option.value = value; input.append(option);
    }
    holder.append(input); fields.append(holder); controls[key] = input; return input;
  };
  add("engine", "参照元DB", [["postgres", "PostgreSQL"], ["influxdb", "InfluxDB 1.x"]]);
  add("database", "参照DB名（空欄なら接続設定と同じ）");
  add("table", "参照テーブル・measurement").placeholder = "t_site";
  add("match_column", "送信値と比較する列").placeholder = "location_id";
  add("value_column", "取得する列").placeholder = "site_id";
  add("cardinality", "参照結果の件数", [["one", "1件を要求（複数は未確認）"], ["many", "取得した全件を使う"]]);
  add("value_type", "取得値の型", [["as_is", "そのまま"], ["string", "文字列"], ["integer", "整数"], ["number", "数値"], ["boolean", "boolean"]]);
  add("on_empty", "参照結果が0件のとき", [["unverified", "未確認として停止"], ["empty", "空配列の応答を期待"], ["status", "指定エラーを期待"]]);
  const status = add("empty_status", "0件時の期待エラーステータス");
  status.type = "number"; status.min = "400"; status.max = "499"; status.closest("label").hidden = true;
  controls.on_empty.addEventListener("change", () => { status.closest("label").hidden = controls.on_empty.value !== "status"; });
  const sync = () => {
    fields.hidden = !toggle.checked; operator.disabled = toggle.checked;
    if (toggle.checked) operator.value = controls.cardinality.value === "one" ? "=" : "in";
    if (parameter.source !== "body") valueCell.textContent = toggle.checked ? "上のQuery/Path欄に送信値を入力" : "DBから選択";
    syncMappedQueryParams();
  };
  toggle.addEventListener("change", sync); controls.cardinality.addEventListener("change", sync);
  fields.append(make("p", "field-caption", "取得値をこの行のDB列に使います。APIへの送信値は変更しません。接続先・認証は詳細設定の同じDB種類の設定を使います。"));
  lookupCell.append(label, fields); row.append(lookupCell);
  container.append(row);
}

function renderWriteMappings(operation) {
  const holder = byId("dbscenario-editor-write-mappings");
  holder.replaceChildren();
  const fields = schemaFields(operation.requestSchema || {});
  const bodyField = byId("dbscenario-editor-request-body-field");
  bodyField.hidden = fields.length > 0;
  if (!fields.length) {
    const row = make("tr", "db-scenario-map-empty");
    const cell = make("td", "field-caption", "OpenAPIに項目schemaがないため、下のJSON欄へbodyを入力してください。");
    cell.colSpan = 6;
    row.append(cell);
    holder.append(row);
    return;
  }
  const bodySample = sampleValue(operation.requestSchema || {}, "value");
  for (const field of fields) {
    addWriteMappingRow(holder, field, valueAtPath(bodySample, field.path));
  }
}

function renderReadMappings(operation) {
  const holder = byId("dbscenario-editor-read-mappings");
  const previousColumns = new Map(
    [...holder.querySelectorAll("tr[data-response-path]")]
      .map((row) => [row.dataset.responsePath, row.querySelector("input[data-db-column]")?.value || ""]),
  );
  holder.replaceChildren();
  const responseSchema = byId("dbscenario-editor-response-shape").value === "array"
    ? schemaAtPath(operation.responseSchema, byId("dbscenario-editor-response-array-path").value || "$")
    : operation.responseSchema;
  const fields = schemaFields(responseSchema || {}, "", 0, "response");
  if (!fields.length) {
    const row = make("tr", "db-scenario-map-empty");
    const cell = make("td", "field-caption", "OpenAPIにJSONレスポンス項目が定義されていません。");
    cell.colSpan = 2;
    row.append(cell);
    holder.append(row);
    return;
  }
  for (const field of fields) {
    addReadMappingRow(holder, field);
    const row = holder.lastElementChild;
    row.querySelector("input[data-db-column]").value = previousColumns.get(field.path) || "";
  }
}

function responseValueFields(operation, shape, arrayPath) {
  return schemaFields(operation.responseSchema || {}, "", 0, "response")
    .filter((field) => !["array", "object"].includes(field.type))
    .filter((field) => shape !== "array" || (arrayPath !== "$" && !field.path.startsWith(`${arrayPath}.`)));
}

function requestValueFields(operation) {
  return [
    ...schemaFields(operation.requestSchema || {}).map((field) => ({ ...field, source: "body" })),
    ...(operation.parameters || []).filter((parameter) => ["query", "path"].includes(parameter.in))
      .map((parameter) => ({ path: parameter.name, source: parameter.in, schema: parameter.schema || {},
        type: schemaType(parameter.schema) })),
  ];
}

function renderResponseValues(operation) {
  const holder = byId("dbscenario-editor-response-values");
  const previous = new Map([...holder.querySelectorAll("tr[data-value-path]")].map((row) => [row.dataset.valuePath, {
    mode: row.querySelector("[data-value-mode]").value,
    parameter: row.querySelector("[data-value-parameter]").value,
    fixed: row.querySelector("[data-value-fixed]").value,
  }]));
  holder.replaceChildren();
  const fields = responseValueFields(operation, byId("dbscenario-editor-response-shape").value,
    byId("dbscenario-editor-response-array-path").value || "$");
  byId("dbscenario-editor-response-values-field").hidden = !fields.length;
  for (const field of fields) {
    const row = make("tr");
    row.dataset.valuePath = field.path;
    row.append(make("td", "", schemaFieldLabel(field)));
    const mode = make("select");
    mode.dataset.valueMode = "true";
    mode.setAttribute("aria-label", `${field.path}の値の照合方法`);
    for (const [value, label] of [["none", "型・形式のみ"], ["request", "送信値と一致"],
      ["requestWithDefault", "送信値と一致（省略時は固定値）"],
      ["requestIfPresent", "送信値と一致（指定時のみ）"], ["fixed", "固定値と一致"]]) {
      const option = make("option", "", label);
      option.value = value;
      mode.append(option);
    }
    mode.value = previous.get(field.path)?.mode || "none";
    const modeCell = make("td");
    modeCell.append(mode);
    row.append(modeCell);
    const parameter = make("select");
    parameter.dataset.valueParameter = "true";
    parameter.setAttribute("aria-label", `${field.path}の照合元の送信項目`);
    const placeholder = make("option", "", "送信項目を選択");
    placeholder.value = "";
    parameter.append(placeholder);
    for (const input of requestValueFields(operation)) {
      const option = make("option", "", `${input.source}: ${input.path}`);
      option.value = `${input.source}:${input.path}`;
      parameter.append(option);
    }
    parameter.value = previous.get(field.path)?.parameter || "";
    const fixed = make("input");
    fixed.type = "text";
    fixed.dataset.valueFixed = "true";
    fixed.placeholder = '固定値（JSON）。例: 1 / "2026-01-01T00:00:00Z"';
    fixed.setAttribute("aria-label", `${field.path}の期待する固定値`);
    fixed.value = previous.get(field.path)?.fixed || "";
    const sourceCell = make("td");
    sourceCell.append(parameter, fixed);
    row.append(sourceCell);
    const sync = () => {
      parameter.hidden = !mode.value.startsWith("request");
      fixed.hidden = !["fixed", "requestWithDefault"].includes(mode.value);
    };
    mode.addEventListener("change", sync);
    sync();
    holder.append(row);
  }
}

function buildResponseValues(form) {
  const available = new Map(responseValueFields(form.operation, form.responseShape,
    form.responseArrayPath || "$").map((field) => [field.path, field]));
  const seen = new Set();
  return (form.responseValues || []).filter((item) => item.mode !== "none").map((item) => {
    const field = available.get(item.path);
    if (!field || seen.has(item.path)) throw new Error(`レスポンス項目「${item.path}」の値照合設定を確認してください`);
    seen.add(item.path);
    const comparison = field.schema?.format === "date-time" ? "date-time" : "exact";
    if (item.mode === "fixed") {
      const value = parseJson(item.fixed, `${item.path}の期待値`, false);
      validateBodyValue(value, field.schema, item.path);
      return { path: item.path, source: "fixed", value, comparison };
    }
    if (!["request", "requestIfPresent", "requestWithDefault"].includes(item.mode)) throw new Error("値の照合方法を選択してください");
    const input = requestValueFields(form.operation).find((candidate) => `${candidate.source}:${candidate.path}` === item.parameter);
    if (!input) throw new Error(`${item.path}の照合元の送信項目を選択してください`);
    if (input.type !== field.type && ![input.type, field.type].every((type) => ["integer", "number"].includes(type))) {
      throw new Error(`${item.path}と送信項目${input.path}の型が一致しません`);
    }
    if (comparison === "date-time" && input.schema?.format !== "date-time") {
      throw new Error(`${item.path}の照合元はdate-time項目を選択してください`);
    }
    if (input.source === "body" && item.mode === "request" && valueAtPath(form.requestBody, input.path) === undefined) {
      throw new Error(`${item.path}の照合元${input.path}が省略されています。「指定時のみ」を選ぶか、個別ケースにしてください`);
    }
    let value;
    if (item.mode === "requestWithDefault") {
      value = parseJson(item.fixed, `${item.path}の省略時の期待値`, false);
      validateBodyValue(value, field.schema, item.path);
    }
    return { path: item.path, source: input.source, parameter: input.path, comparison,
      when_missing: item.mode === "requestIfPresent" ? "skip" : item.mode === "requestWithDefault" ? "fixed" : "error",
      ...(item.mode === "requestWithDefault" ? { value } : {}) };
  });
}

function renderReadFilters(operation) {
  const holder = byId("dbscenario-editor-read-filters");
  holder.replaceChildren();
  const requestSchema = operation.requestSchema || {};
  const requestRequired = new Set(requestSchema.required || []);
  const presenceRules = requestSchema["x-otg-presence-rules"] || [];
  const preferredPresence = new Set(presenceRules.filter((rule) => rule.kind === "atLeastOne")
    .map((rule) => rule.fields?.[0]).filter(Boolean));
  const params = [
    ...schemaFields(requestSchema).filter((field) => field.path !== "$" && !field.path.includes(".") && !field.path.includes("[]"))
      .map((field) => ({ source: "body", name: field.path, format: field.schema?.format || "",
        required: requestRequired.has(field.path),
        defaultValue: requestRequired.has(field.path) || preferredPresence.has(field.path)
          ? sampleValue(field.schema, field.path) : undefined })),
    ...(operation.parameters || [])
      .filter((parameter) => ["query", "path"].includes(parameter.in))
      .map((parameter) => ({
        source: parameter.in,
        name: parameter.name,
        format: parameter.schema?.format || "",
        required: parameter.in === "path" || !!parameter.required,
      })),
    ...[...operation.path.matchAll(/\{([^}]+)\}/g)]
      .map((match) => ({ source: "path", name: match[1], required: true, format: "" })),
  ];
  const seen = new Set();
  for (const parameter of params) {
    const key = `${parameter.source}:${parameter.name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    addReadFilterRow(holder, parameter);
  }
  if (!seen.size) {
    const row = make("tr", "db-scenario-map-empty");
    const cell = make("td", "field-caption", "OpenAPIに検索用のBody/Path/Queryパラメータがありません。");
    cell.colSpan = 6;
    row.append(cell);
    holder.append(row);
  }
}

function syncMappedQueryParams() {
  const mapped = new Set(
    [...byId("dbscenario-editor-read-filters").querySelectorAll('tr[data-parameter-source="query"]')]
      .filter((row) => row.querySelector("input[data-db-column]")?.value.trim() && !row.querySelector("[data-lookup-enabled]")?.checked)
      .map((row) => row.dataset.parameterName),
  );
  for (const input of byId("dbscenario-editor-query-param-rows").querySelectorAll("input[data-query-param-name]")) {
    const shouldAutoFill = mapped.has(input.dataset.queryParamName);
    if (shouldAutoFill && !input.disabled) {
      input.dataset.previousValue = input.value;
      input.value = "";
      input.disabled = true;
      input.placeholder = "DBの値から自動生成";
    } else if (!shouldAutoFill && input.disabled) {
      input.disabled = false;
      input.value = input.dataset.previousValue || "";
      input.placeholder = input.dataset.required === "true" ? "必須値" : "空欄なら送信しません";
    }
  }
}

function collectPathParams() {
  const params = {};
  const holder = byId("dbscenario-editor-path-param-rows");
  for (const input of holder.querySelectorAll("input[data-param-name]")) {
    const autoCheckbox = [...holder.querySelectorAll("input[data-auto-path-param]")]
      .find((item) => item.dataset.autoPathParam === input.dataset.paramName);
    if (autoCheckbox?.checked) {
      params[input.dataset.paramName] = input.dataset.autoValue;
      continue;
    }
    const value = input.value.trim();
    if (!value) throw new Error(`パスパラメータ「${input.dataset.paramName}」を入力してください`);
    params[input.dataset.paramName] = parseScalar(value, `パスパラメータ「${input.dataset.paramName}」`);
  }
  return params;
}

function collectWriteMappings(body) {
  const rows = [...byId("dbscenario-editor-write-mappings").querySelectorAll("tr")];
  const columns = {};
  const where = {};
  for (const row of rows) {
    if (!row.dataset.fieldPath) continue;
    const targetInput = row.querySelector('input[aria-label="DBカラム"]');
    const transformSelect = row.querySelector('select[aria-label="値の変換"]');
    const fixedInput = row.querySelector('input[aria-label="固定値"]');
    const source = row.dataset.fieldPath;
    const target = targetInput.value.trim();
    const transform = transformSelect.value;
    if (!target) continue;
    requireDbIdentifier(target, "DBカラム");
    if (Object.hasOwn(columns, target)) throw new Error(`DBカラム「${target}」の対応が重複しています`);
    let expected;
    if (transform === "fixed") {
      expected = parseScalar(fixedInput.value, `DBカラム「${target}」の固定値`);
    } else {
      expected = valueAtPath(body, source);
      if (expected === undefined) throw new Error(`リクエストbodyに「${source}」がありません`);
      if (transform === "lower" || transform === "upper") {
        if (typeof expected !== "string") throw new Error(`「${source}」は文字列なので、文字の変換を使えます`);
        expected = transform === "lower" ? expected.toLowerCase() : expected.toUpperCase();
      }
    }
    columns[target] = expected;
    if (row.querySelector('input[aria-label="保存後の照合に使う"]')?.checked) where[target] = expected;
  }
  return { columns, where };
}

function setBodyValueAtPath(body, path, value) {
  if (path === "$") return value;
  const parts = String(path).replace(/\[\]/g, ".0").split(".").filter(Boolean);
  let current = body;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const key = parts[index];
    const nextKey = parts[index + 1];
    if (!current[key] || typeof current[key] !== "object") {
      current[key] = /^\d+$/.test(nextKey) ? [] : {};
    }
    current = current[key];
  }
  current[parts.at(-1)] = value;
  return body;
}

function requestValueFromRow(row) {
  const editor = row.querySelector("[data-api-value]");
  const type = schemaType(row.requestSchema) || "value";
  const label = `API項目「${row.dataset.fieldPath}」`;
  if (editor.tagName === "TEXTAREA" || editor.tagName === "SELECT") {
    return parseJson(editor.value, label, false);
  }
  if (type === "integer" || type === "number") {
    if (!editor.value.trim()) throw new Error(`${label}の数値を入力してください`);
    const value = Number(editor.value);
    if (!Number.isFinite(value) || (type === "integer" && !Number.isInteger(value))) {
      throw new Error(`${label}は${type === "integer" ? "整数" : "数値"}で入力してください`);
    }
    return value;
  }
  return editor.value;
}

function collectRequestBodyFromFields() {
  let body = {};
  for (const row of byId("dbscenario-editor-write-mappings").querySelectorAll("tr[data-field-path]")) {
    const include = row.querySelector("input[data-include-field]");
    if (include && !include.checked) continue;
    const value = requestValueFromRow(row);
    if (row.dataset.fieldPath === "$") return value;
    body = setBodyValueAtPath(body, row.dataset.fieldPath, value);
  }
  return body;
}

export function buildDbScenario(form) {
  const { operation } = form;
  if (!operation) throw new Error("API操作を選択してください");
  const engine = form.engine || "postgres";
  if (!["postgres", "influxdb"].includes(engine)) throw new Error("対応DBはPostgreSQLまたはInfluxDBです");
  const name = String(form.name || "").trim();
  const table = String(form.table || "").trim();
  if (!name) throw new Error("試験名を入力してください");
  if (form.mode === "sql_response") return buildSqlResponseScenario({ ...form, name });
  if (!table) throw new Error("対象テーブルを入力してください");
  requireDbIdentifier(table, "対象テーブル");

  const method = operation.method.toUpperCase();
  if (!MUTATING_METHODS.has(method) && method !== "GET") {
    throw new Error("GET / POST / PUT / PATCH / DELETE の操作を選んでください");
  }
  const scenario = {
    name,
    request: {
      operationId: operation.operationId,
      path_params: { ...(form.pathParams || {}) },
      query_params: { ...(form.queryParams || {}) },
    },
  };
  if (form.mode === "insert_rows") return buildInsertScenario(form);
  if (form.mode === "unchanged") {
    const status = Number(form.unchangedStatus);
    if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error("期待するHTTP statusを100〜599の整数で入力してください");
    const columns = String(form.unchangedColumns || "").split(",").map((name) => name.trim());
    if (!columns.length || columns.some((name) => !name)) throw new Error("比較するDB列を入力してください");
    columns.forEach((name) => requireDbIdentifier(name, "比較するDB列"));
    if (new Set(columns).size !== columns.length) throw new Error("比較するDB列が重複しています");
    const where = form.unchangedWhere || {};
    if (typeof where !== "object" || Array.isArray(where)) throw new Error("比較する行の条件をJSONオブジェクトで入力してください");
    for (const [column, value] of Object.entries(where)) {
      requireDbIdentifier(column, "比較する行の条件");
      if (value !== null && !["string", "number", "boolean"].includes(typeof value)) throw new Error("比較する行の条件は単一の値を入力してください");
    }
    scenario.request.body = form.requestBody || {};
    scenario.response_check = { expect: { status } };
    const influx = {};
    if (engine === "influxdb") {
      if (!form.timeStart || !form.timeEnd) throw new Error("InfluxDBの比較期間の開始・終了を入力してください");
      influx.engine = engine; influx.time_start = form.timeStart; influx.time_end = form.timeEnd;
      if (Object.values(where).some((value) => value === null)) throw new Error("InfluxDBの行条件にはnullを指定できません");
    }
    scenario.db_unchanged = [{ table, columns, where, ...influx }];
    return scenario;
  }
  if (engine === "influxdb" && method !== "GET") {
    const action = form.influxAction || ({ POST: "insert", PUT: "update", PATCH: "update", DELETE: "delete" })[method];
    if (!["insert", "update", "delete"].includes(action)) throw new Error("期待する変更を選択してください");
    const status = Number(form.influxStatus);
    if (!Number.isInteger(status) || status < 200 || status > 299) throw new Error("変更確認の成功statusを200〜299で指定してください");
    const time = String(form.influxTime || "").trim();
    if (!time) throw new Error("ポイント時刻を入力してください");
    const tags = form.influxTags || {};
    if (typeof tags !== "object" || Array.isArray(tags)) throw new Error("全タグをJSONオブジェクトで指定してください");
    for (const [key, value] of Object.entries(tags)) {
      requireDbIdentifier(key, "タグ名");
      if (key === "time" || typeof value !== "string" || !value) throw new Error("タグ値は空でない文字列にしてください");
    }
    const fields = {};
    if (action !== "delete") {
      for (const [key, value] of Object.entries(form.influxFields || {})) {
        requireDbIdentifier(key, "フィールド名");
        if (key === "time" || Object.hasOwn(tags, key)) continue;
        if (value === null || !["string", "number", "boolean"].includes(typeof value)) throw new Error("InfluxDBフィールドには文字列・数値・booleanを指定してください");
        fields[key] = value;
      }
      if (!Object.keys(fields).length) throw new Error("API項目に比較するInfluxDBフィールドを対応付けてください");
    }
    scenario.request.body = form.requestBody || {};
    scenario.response_check = { expect: { status } };
    scenario.influx_mutation = { measurement: table, time, tags, fields, action, preserve_unmapped: !!form.influxPreserve };
    if (form.influxFixture) {
      const seeds = action === "insert" ? {} : (form.influxSeedFields || {});
      if (action !== "insert" && !Object.keys(seeds).length) throw new Error("初期フィールドを1件以上入力してください");
      scenario.influx_mutation.fixture = { fields: seeds };
    }
    return scenario;
  }
  if (MUTATING_METHODS.has(method)) {
    const writeStatus = Number(form.writeStatus);
    if (!Number.isInteger(writeStatus) || writeStatus < 100 || writeStatus > 599) {
      throw new Error("期待する成功statusは100〜599の整数で指定してください");
    }
    scenario.response_check = { expect: { status: writeStatus } };
  }

  if (method === "GET") {
    validateComparisonBody(form.requestBody || {}, operation.requestSchema);
    for (const rule of operation.requestSchema?.["x-otg-presence-rules"] || []) {
      const [first, second] = rule.fields || [];
      const firstSent = Object.hasOwn(form.requestBody || {}, first);
      const secondSent = Object.hasOwn(form.requestBody || {}, second);
      if (rule.kind === "atLeastOne" && !firstSent && !secondSent) {
        throw new Error(`Bodyの「${first}」または「${second}」を入力してください`);
      }
      if (rule.kind === "together" && firstSent !== secondSent) {
        throw new Error(`Bodyの「${first}」と「${second}」は両方入力するか、両方省略してください`);
      }
    }
    const mapping = form.readMappings || [];
    if (!mapping.length) throw new Error("OpenAPIに表示されたレスポンス項目のうち、DBと照合する項目のDBカラムを入力してください");
    const responseFields = {};
    for (const item of mapping) {
      const source = String(item.source || "").trim();
      const target = String(item.target || "").trim();
      if (!source || !target) throw new Error("DBカラムとレスポンス項目を対応行ごとに入力してください");
      requireDbIdentifier(source, "DBカラム");
      if (Object.hasOwn(responseFields, target)) throw new Error(`レスポンス項目「${target}」の対応が重複しています`);
      responseFields[target] = source;
    }
    const filters = (form.readFilters || []).map((item) => {
      const source = String(item.source || "").trim();
      const parameter = String(item.parameter || "").trim();
      const column = String(item.column || "").trim();
      const operator = String(item.operator || "").trim();
      if (!["query", "path", "body"].includes(source) || !parameter || !column) return null;
      requireDbIdentifier(column, "検索に使うDBカラム");
      if (!["=", ">", ">=", "<", "<=", "in"].includes(operator)) throw new Error("比較条件を選択してください");
      if (operator === "in" && source !== "body" && !item.lookup) throw new Error("IN条件はBodyの配列項目で指定してください");
      if (item.group && source !== "body") throw new Error("ORグループはBody項目で指定してください");
      const lookup = item.lookup ? buildLookup(item.lookup, operator) : null;
      if (lookup && source !== "body" && !Object.hasOwn(source === "query" ? scenario.request.query_params : scenario.request.path_params, parameter)) {
        throw new Error(`別DB参照に使う${source}「${parameter}」の送信値を入力してください`);
      }
      return { source, parameter, column, operator, auto: source !== "body" && !lookup, format: item.format || null,
        ...(item.group ? { group: item.group } : {}), ...(lookup ? { lookup } : {}) };
    }).filter(Boolean);
    const seenFilters = new Set();
    for (const filter of filters) {
      const key = `${filter.source}:${filter.parameter}`;
      if (seenFilters.has(key)) throw new Error(`APIパラメータ「${filter.parameter}」の対応が重複しています`);
      seenFilters.add(key);
    }
    const mappedPathParams = new Set(filters.filter((item) => item.source === "path").map((item) => item.parameter));
    const mappedQueryParams = new Set(filters.filter((item) => item.source === "query").map((item) => item.parameter));
    for (const match of operation.path.matchAll(/\{([^}]+)\}/g)) {
      if (!mappedPathParams.has(match[1])) {
        throw new Error(`GETのパスパラメータ「${match[1]}」の行にDBカラムを入力してください`);
      }
    }
    for (const parameter of operation.parameters || []) {
      if (parameter.in === "query" && parameter.required && !mappedQueryParams.has(parameter.name)) {
        throw new Error(`必須Query「${parameter.name}」の行にDBカラムを入力してください`);
      }
    }
    for (const parameter of Object.keys(scenario.request.query_params)) {
      if (!mappedQueryParams.has(parameter)) {
        throw new Error(`Query「${parameter}」の値をDB検索条件に対応付けてください`);
      }
    }
    const mappedBodyParams = new Set(filters.filter((item) => item.source === "body").map((item) => item.parameter));
    for (const name of Object.keys(form.requestBody || {})) {
      if (!mappedBodyParams.has(name)) throw new Error(`Body「${name}」の値をDB検索条件に対応付けてください`);
    }
    for (const filter of filters) {
      if (!filter.lookup && filter.source === "query") delete scenario.request.query_params[filter.parameter];
      else if (!filter.lookup && filter.source === "path") delete scenario.request.path_params[filter.parameter];
    }
    const status = Number(form.responseStatus);
    if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error("期待statusは100〜599の整数で指定してください");
    if (!["object", "array"].includes(form.responseShape)) {
      throw new Error("OpenAPIのレスポンス形式が判別できません。単一オブジェクトか配列か選択してください");
    }
    const selectedResponseSchema = form.responseShape === "array"
      ? schemaAtPath(operation.responseSchema, form.responseArrayPath || "$")
      : operation.responseSchema;
    if (schemaType(selectedResponseSchema) !== form.responseShape) {
      throw new Error("選択したレスポンス形式・配列パスがOpenAPIのレスポンスschemaと一致しません");
    }
    const responseValues = buildResponseValues(form);
    scenario.response_check = { expect: { status, ...(responseValues.length ? { values: responseValues } : {}) } };
    scenario.request.body = form.requestBody || {};
    scenario.db_response_check = {
      ...(engine === "influxdb" ? { engine } : {}),
      table,
      fields: responseFields,
      filters,
      array_path: form.responseShape === "array" ? String(form.responseArrayPath || "$") : null,
    };
    return scenario;
  }

  if (method === "DELETE") {
    const primaryKey = String(form.primaryKey || "").trim();
    const fields = form.seedFields;
    if (!primaryKey) throw new Error("主キーカラムを入力してください");
    requireDbIdentifier(primaryKey, "主キーカラム");
    if (!Object.keys(fields).length) throw new Error("削除対象として事前データを1項目以上入力してください");
    scenario.given = [{ table, as: "record", fields }];
    scenario.db_check = {
      table,
      where: { [primaryKey]: `{{given.record.${primaryKey}}}` },
      expect: { exists: false },
    };
    if (form.softDelete) {
      const column = String(form.softDeleteColumn || "").trim();
      if (!column) throw new Error("論理削除のカラム名を入力してください");
      requireDbIdentifier(column, "論理削除カラム");
      scenario.db_check.expect = {
        exists: true,
        columns: { [column]: parseScalar(form.softDeleteValue, "論理削除後の値") },
      };
    }
    return scenario;
  }

  const body = form.requestBody;
  if (method === "POST" || method === "PUT" || method === "PATCH") {
    if (method === "PUT" || method === "PATCH") {
      const primaryKey = String(form.primaryKey || "").trim();
      if (!primaryKey) throw new Error("主キーカラムを入力してください");
      requireDbIdentifier(primaryKey, "主キーカラム");
      const fields = form.seedFields;
      if (!Object.keys(fields).length) throw new Error("更新前のDBデータを1項目以上入力してください");
      scenario.given = [{ table, as: "record", fields }];
    }
    scenario.request.body = body;
    const { columns, where } = collectWriteMappings(body);
    const cleanupWhere = { ...where };
    if (!Object.keys(columns).length) throw new Error("OpenAPIに表示されたリクエスト項目のうち、DBで確認する項目のDBカラムを入力してください");
    if (method === "POST") {
      const responsePath = String(form.responseRowPath || "").trim();
      const responseColumn = String(form.responseRowColumn || "").trim();
      if (Boolean(responsePath) !== Boolean(responseColumn)) {
        throw new Error("レスポンスのID項目と対応するDB列は両方入力してください");
      }
      if (responsePath) {
        if (!/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(responsePath)) {
          throw new Error("レスポンスのID項目はドット区切りの項目パスで入力してください");
        }
        requireDbIdentifier(responseColumn, "レスポンスIDに対応するDB列");
        if (Object.hasOwn(where, responseColumn)) {
          throw new Error(`行特定に使うDB列「${responseColumn}」が重複しています`);
        }
        where[responseColumn] = `{{response.${responsePath}}}`;
      }
    }
    if (method === "POST" && !Object.keys(where).length) {
      throw new Error("保存された行を特定するため、リクエスト項目の列を選ぶか、レスポンスのID項目を入力してください");
    }
    scenario.db_check = {
      table,
      where: method === "POST"
        ? where
        : { [form.primaryKey]: `{{given.record.${form.primaryKey}}}` },
      expect: { exists: true, columns },
    };
    if (method === "POST" && form.postCleanup) {
      if (!Object.keys(cleanupWhere).length) {
        throw new Error("POST後に行を片付ける場合は、リクエスト項目から保存行の特定に使う列も選んでください");
      }
      const primaryKey = String(form.postCleanupPrimaryKey || "").trim();
      if (!primaryKey) throw new Error("POST後の片付けに使う主キー列を入力してください");
      requireDbIdentifier(primaryKey, "POST後の片付けに使う主キー列");
      scenario.cleanup = { table, primary_key: primaryKey, where: cleanupWhere };
    }
  }
  return scenario;
}

function buildLookup(raw, operator) {
  for (const key of ["table", "match_column", "value_column"]) requireDbIdentifier(raw[key], `別DB参照の${key}`);
  if (!["postgres", "influxdb"].includes(raw.engine)) throw new Error("参照元DBを選択してください");
  if (!["one", "many"].includes(raw.cardinality) || operator !== (raw.cardinality === "one" ? "=" : "in")) {
    throw new Error("別DB参照は1件なら=、全件ならINで比較してください");
  }
  if (!["as_is", "string", "integer", "number", "boolean"].includes(raw.value_type || "as_is")) throw new Error("取得値の型を選択してください");
  if (!["unverified", "empty", "status"].includes(raw.on_empty)) throw new Error("参照結果が0件の場合の扱いを選択してください");
  const lookup = { engine: raw.engine, table: raw.table, match_column: raw.match_column, value_column: raw.value_column,
    cardinality: raw.cardinality, value_type: raw.value_type || "as_is", on_empty: raw.on_empty,
    ...(raw.database?.trim() ? { database: raw.database.trim() } : {}) };
  if (raw.on_empty === "status") {
    const status = Number(raw.empty_status);
    if (!Number.isInteger(status) || status < 400 || status > 499) throw new Error("参照結果0件の期待statusを400〜499で入力してください");
    lookup.empty_status = status;
  }
  return lookup;
}

export function buildDbScenarios(form) {
  const base = buildDbScenario(form);
  if (form.mode === "unchanged" || form.operation.method.toUpperCase() !== "GET" || !form.expandCombinations) return [base];
  const schema = form.operation.requestSchema || {};
  const rules = schema["x-otg-presence-rules"] || [];
  const values = form.requestBody || {};
  let bodies = [{ ...values }];
  const expand = (variants) => {
    if (bodies.length * variants.length > 64) {
      throw new Error("組み合わせが64件を超えます。対応設定を分けるか、組み合わせ生成を外してください");
    }
    bodies = bodies.flatMap((body) => variants.map((mutate) => mutate({ ...body })));
  };
  for (const rule of rules) {
    const [first, second] = rule.fields;
    for (const name of rule.fields) {
      if (!Object.hasOwn(values, name)) throw new Error(`組み合わせ用に「${name}」の値を入力してください。DBにある試験値を指定してください`);
      validateBodyValue(values[name], schema.properties?.[name] || {}, name);
    }
    const choices = rule.kind === "atLeastOne" ? [[first], [second], [first, second]] : [[], [first, second]];
    expand(choices.map((selected) => (body) => {
      delete body[first];
      delete body[second];
      for (const name of selected) body[name] = values[name];
      return body;
    }));
  }
  for (const filter of base.db_response_check.filters) {
    if (filter.lookup || filter.source !== "body" || filter.operator !== "in") continue;
    const name = filter.parameter;
    const array = values[name];
    if (!Array.isArray(array)) throw new Error(`IN条件の「${name}」には配列値を入力してください`);
    const minimum = schema.properties?.[name]?.minItems || 0;
    if (minimum > 1 || array.length < 2) continue;
    const choices = [array, ...array.map((item) => [item])];
    expand(choices.map((value) => (body) => {
      if (Object.hasOwn(body, name)) body[name] = value;
      return body;
    }));
  }
  const seen = new Set();
  bodies = bodies.filter((body) => {
    const valid = rules.every((rule) => {
      const sent = rule.fields.map((name) => Object.hasOwn(body, name));
      return rule.kind === "atLeastOne" ? sent.some(Boolean) : sent[0] === sent[1];
    });
    const key = JSON.stringify(Object.keys(body).sort().map((name) => [name, body[name]]));
    if (!valid || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  if (!bodies.length) throw new Error("必須条件を満たす組み合わせがありません");
  return bodies.map((body, index) => ({
    ...buildDbScenario({ ...form, requestBody: body }),
    name: `${base.name}（組み合わせ${index + 1}: ${Object.keys(body).join("・")}）`,
  }));
}

export function initDbScenarioEditor({ invoke, saveDialog, onSaved }) {
  let operations = [];
  let scenarios = [];
  let renderedOperationId = "";

  function addInfluxSeed() {
    const row = make("tr");
    const name = make("input"); name.setAttribute("aria-label", "初期フィールド名"); name.dataset.seedName = "";
    const type = make("select"); type.setAttribute("aria-label", "初期フィールドの型"); type.dataset.seedType = "";
    for (const kind of ["float", "integer", "string", "boolean"]) {
      const option = make("option", "", kind); option.value = kind; type.append(option);
    }
    const value = make("input"); value.setAttribute("aria-label", "初期値"); value.dataset.seedValue = "";
    const remove = make("button", "secondary", "削除"); remove.type = "button"; remove.addEventListener("click", () => row.remove());
    for (const control of [name, type, value, remove]) { const cell = make("td"); cell.append(control); row.append(cell); }
    byId("dbscenario-editor-influx-seeds").append(row);
  }

  function collectInfluxSeeds() {
    if (!byId("dbscenario-editor-influx-fixture").checked || byId("dbscenario-editor-influx-action").value === "insert") return {};
    const fields = {};
    for (const row of byId("dbscenario-editor-influx-seeds").querySelectorAll("tr")) {
      const name = row.querySelector("[data-seed-name]").value.trim();
      requireDbIdentifier(name, "初期フィールド名");
      if (Object.hasOwn(fields, name)) throw new Error("初期フィールド名が重複しています");
      const type = row.querySelector("[data-seed-type]").value;
      const text = row.querySelector("[data-seed-value]").value;
      let value = text;
      if (type === "boolean") {
        if (!["true", "false"].includes(text.trim())) throw new Error("booleanの初期値はtrueまたはfalseを入力してください");
        value = text.trim() === "true";
      } else if (type !== "string") {
        value = Number(text);
        if (!text.trim() || !Number.isFinite(value) || (type === "integer" && !Number.isSafeInteger(value))) throw new Error("初期値に型に合う数値を入力してください（整数は安全に扱える範囲）");
      }
      fields[name] = { type, value };
    }
    return fields;
  }

  const setStatus = (message, state = "") => {
    const status = byId("dbscenario-editor-status");
    status.textContent = message;
    status.classList.toggle("ok", state === "ok");
    status.classList.toggle("error", state === "error");
  };

  const selectedOperation = () => operations.find((item) => item.operationId === byId("dbscenario-editor-operation").value);
  const sqlEditor = initSqlResponseEditor(() => selectedOperation());
  const insertEditor = initInsertEditor(() => selectedOperation());

  function renderOperations() {
    const select = byId("dbscenario-editor-operation");
    const previous = select.value;
    select.replaceChildren();
    const prompt = make("option", "", operations.length ? "API操作を選択してください" : "OpenAPIの操作がありません");
    prompt.value = "";
    select.append(prompt);
    for (const operation of operations) {
      const option = make("option", "", `${operation.method} ${operation.path}（${operation.operationId}）`);
      option.value = operation.operationId;
      select.append(option);
    }
    if (operations.some((item) => item.operationId === previous)) select.value = previous;
    renderForOperation();
  }

  function renderPathParams(operation) {
    const holder = byId("dbscenario-editor-path-param-rows");
    holder.replaceChildren();
    const names = [...(operation.path.matchAll(/\{([^}]+)\}/g))].map((match) => match[1]);
    byId("dbscenario-editor-path-params").hidden = names.length === 0 || operation.method.toUpperCase() === "GET";
    if (operation.method.toUpperCase() === "GET") return;
    for (const name of names) {
      const row = make("div", "db-scenario-path-param-row");
      const label = make("label", "", name);
      label.htmlFor = `dbscenario-path-param-${name}`;
      const input = make("input");
      input.id = `dbscenario-path-param-${name}`;
      input.type = "text";
      input.dataset.paramName = name;
      input.setAttribute("aria-label", `パスパラメータ ${name}`);
      input.placeholder = "例: 42";
      const primaryKey = byId("dbscenario-editor-primary-key").value.trim();
      if (SEEDED_METHODS.has(operation.method) && primaryKey) {
        const valueHolder = make("div", "db-scenario-path-param-value");
        const autoLabel = make("label", "checkbox", "DBの主キーを使う");
        const autoCheckbox = make("input");
        autoCheckbox.type = "checkbox";
        autoCheckbox.checked = false;
        autoCheckbox.dataset.autoPathParam = name;
        autoCheckbox.setAttribute("aria-label", `${name}にDBの主キーを使う`);
        input.dataset.autoValue = `{{given.record.${primaryKey}}}`;
        input.placeholder = "例: 42";
        autoLabel.prepend(autoCheckbox);
        autoCheckbox.addEventListener("change", () => {
          input.disabled = autoCheckbox.checked;
          if (autoCheckbox.checked) {
            input.dataset.previousValue = input.value;
            input.value = "";
          } else {
            input.value = input.dataset.previousValue || "";
          }
        });
        valueHolder.append(autoLabel, input);
        row.append(label, valueHolder);
      } else {
        row.append(label, input);
      }
      holder.append(row);
    }
  }

  function renderQueryParams(operation) {
    const holder = byId("dbscenario-editor-query-param-rows");
    holder.replaceChildren();
    const parameters = (operation.parameters || []).filter((parameter) => parameter.in === "query");
    byId("dbscenario-editor-query-params").hidden = parameters.length === 0;
    for (const parameter of parameters) {
      const row = make("div", "db-scenario-path-param-row");
      const label = make("label", "", `${parameter.name}${parameter.required ? "（必須）" : "（任意）"}`);
      const input = make("input");
      input.type = "text";
      input.dataset.queryParamName = parameter.name;
      input.dataset.required = String(!!parameter.required);
      const sample = sampleValue(parameter.schema || {}, parameter.name);
      input.value = parameter.required ? (typeof sample === "object" ? JSON.stringify(sample) : String(sample)) : "";
      input.placeholder = parameter.required ? "必須値" : "空欄なら送信しません";
      input.setAttribute("aria-label", `Queryパラメータ ${parameter.name}`);
      row.append(label, input);
      holder.append(row);
    }
  }

  function collectQueryParams() {
    const params = {};
    for (const input of byId("dbscenario-editor-query-param-rows").querySelectorAll("input[data-query-param-name]")) {
      const value = input.value.trim();
      if (value) params[input.dataset.queryParamName] = parseScalar(value, `Queryパラメータ「${input.dataset.queryParamName}」`);
    }
    return params;
  }

  function renderForOperation() {
    const operation = selectedOperation();
    const method = operation?.method || "";
    const operationChanged = operation?.operationId !== renderedOperationId;
    renderedOperationId = operation?.operationId || "";
    if (operationChanged) {
      insertEditor.render();
      sqlEditor.render();
      byId("dbscenario-editor-mode").value = "mapping";
      byId("dbscenario-editor-unchanged-body").value = "{}";
      byId("dbscenario-editor-unchanged-status").value = "";
      byId("dbscenario-editor-unchanged-columns").value = "";
      byId("dbscenario-editor-unchanged-where").value = "{}";
    }
    byId("dbscenario-editor-unchanged-panel").hidden = byId("dbscenario-editor-mode").value !== "unchanged";
    const isGet = method === "GET";
    const hasRequestBody = ["POST", "PUT", "PATCH"].includes(method);
    const usesSeed = SEEDED_METHODS.has(method);
    byId("dbscenario-editor-write-panel").hidden = !hasRequestBody;
    byId("dbscenario-editor-post-cleanup").hidden = method !== "POST";
    byId("dbscenario-editor-post-row-id").hidden = method !== "POST";
    byId("dbscenario-editor-post-cleanup-fields").hidden = method !== "POST" || !byId("dbscenario-editor-post-cleanup-enabled").checked;
    byId("dbscenario-editor-seed-panel").hidden = !usesSeed;
    byId("dbscenario-editor-get-panel").hidden = !isGet;
    byId("dbscenario-editor-soft-delete-option").hidden = method !== "DELETE";
    byId("dbscenario-editor-soft-delete-fields").hidden = method !== "DELETE" || !byId("dbscenario-editor-soft-delete").checked;
    if (!operation) {
      byId("dbscenario-editor-guidance").textContent = "まずAPI操作を選択してください。操作に応じて必要な入力欄だけが表示されます。";
      byId("dbscenario-editor-path-params").hidden = true;
      byId("dbscenario-editor-query-params").hidden = true;
      return;
    }
    const guidance = {
      GET: "GET：既存DBを読み取り、検索条件からリクエスト値と期待レスポンスを作ります。DBへ試験行を追加しません。",
      POST: "POST：テストデータをAPIへ送り、指定したDB列に値が保存されるか確認します。",
      PUT: "PUT：更新前のDB行を用意し、APIに送った値が指定した列へ反映されるか確認します。",
      PATCH: "PATCH：更新前のDB行を用意し、APIに送った値が指定した列へ反映されるか確認します。",
      DELETE: "DELETE：削除対象のDB行を用意し、API実行後に行が消えるか、削除フラグが変わるか確認します。",
    }[method] || "選択したAPI操作に合わせて、DBに確認用データを設定します。";
    byId("dbscenario-editor-guidance").textContent = guidance;
    byId("dbscenario-editor-guidance").dataset.mappingGuidance = guidance;
    if (operationChanged) {
      byId("dbscenario-editor-influx-action").value = ({ POST: "insert", PUT: "update", PATCH: "update", DELETE: "delete" })[method] || "insert";
      byId("dbscenario-editor-influx-status").value = operation.successStatus || "200";
      byId("dbscenario-editor-influx-time").value = "";
      byId("dbscenario-editor-influx-tags").value = "{}";
      byId("dbscenario-editor-influx-delete-body").value = "{}";
      byId("dbscenario-editor-influx-preserve").checked = false;
      byId("dbscenario-editor-influx-fixture").checked = false;
      byId("dbscenario-editor-influx-seeds").replaceChildren();
      byId("dbscenario-editor-expand-combinations").checked = false;
      byId("dbscenario-editor-name").value = `${operation.operationId} のDB検証`;
      byId("dbscenario-editor-table").value = "";
      byId("dbscenario-editor-request-body").value = "";
      byId("dbscenario-editor-seed-fields").value = "";
      byId("dbscenario-editor-write-mappings").replaceChildren();
      byId("dbscenario-editor-read-mappings").replaceChildren();
      byId("dbscenario-editor-read-filters").replaceChildren();
      byId("dbscenario-editor-response-values").replaceChildren();
      byId("dbscenario-editor-primary-key").value = "";
      byId("dbscenario-editor-post-cleanup-enabled").checked = false;
      byId("dbscenario-editor-post-cleanup-primary-key").value = "";
      byId("dbscenario-editor-response-row-path").value = "";
      byId("dbscenario-editor-response-row-column").value = "";
      byId("dbscenario-editor-soft-delete").checked = false;
      byId("dbscenario-editor-soft-delete-column").value = "";
      byId("dbscenario-editor-soft-delete-value").value = "";
      byId("dbscenario-editor-response-array-path").value = "$";
      const defaultStatus = Number(operation.successStatus) || (method === "POST" ? 201 : 200);
      byId("dbscenario-editor-write-status").value = String(defaultStatus);
      byId("dbscenario-editor-response-status").value = String(defaultStatus);
      const responseType = schemaType(operation.responseSchema);
      const arrayProperties = Object.entries(operation.responseSchema?.properties || {})
        .filter(([, schema]) => schemaType(schema) === "array");
      const singleArrayPath = responseType === "object" && arrayProperties.length === 1 ? arrayProperties[0][0] : null;
      if (singleArrayPath) byId("dbscenario-editor-response-array-path").value = singleArrayPath;
      byId("dbscenario-editor-response-shape").value = responseType === "array" || singleArrayPath
        ? "array"
        : responseType === "object" ? "object" : "";
      byId("dbscenario-editor-response-array-path-field").hidden = method !== "GET" || byId("dbscenario-editor-response-shape").value !== "array";
    }
    byId("dbscenario-editor-name").value ||= `${operation.operationId} のDB検証`;
    if (!byId("dbscenario-editor-request-body").value && hasRequestBody) {
      byId("dbscenario-editor-request-body").value = JSON.stringify(sampleValue(operation.requestSchema || {}, "value"), null, 2);
    }
    renderPathParams(operation);
    renderQueryParams(operation);
    if (hasRequestBody) renderWriteMappings(operation);
    if (method === "POST") {
      const choices = byId("dbscenario-editor-response-row-paths");
      choices.replaceChildren();
      for (const field of schemaFields(operation.responseSchema || {}, "", 0, "response")) {
        const option = make("option");
        option.value = field.path;
        choices.append(option);
      }
    }
    if (isGet) {
      renderReadFilters(operation);
      renderReadMappings(operation);
      renderResponseValues(operation);
    }
    syncMappedQueryParams();
    updateMode();
    if (!byId("dbscenario-editor-status").classList.contains("ok")) setStatus("");
  }

  function updateMode() {
    const sql = byId("dbscenario-editor-mode").value === "sql_response";
    byId("dbscenario-sql-panel").hidden = !sql;
    byId("dbscenario-editor-table").hidden = sql;
    document.querySelector('label[for="dbscenario-editor-table"]').hidden = sql;
    const insert = byId("dbscenario-editor-mode").value === "insert_rows";
    byId("dbscenario-insert-panel").hidden = !insert;
    const unchanged = byId("dbscenario-editor-mode").value === "unchanged";
    const influx = byId("dbscenario-editor-engine").value === "influxdb";
    byId("dbscenario-editor-influx-help").hidden = !influx;
    byId("dbscenario-editor-influx-period").hidden = !influx || !unchanged;
    const method = selectedOperation()?.method;
    byId("dbscenario-editor-unchanged-panel").hidden = !unchanged;
    byId("dbscenario-editor-write-panel").hidden = sql || insert || unchanged || !["POST", "PUT", "PATCH"].includes(method);
    byId("dbscenario-editor-seed-panel").hidden = sql || insert || influx || unchanged || !SEEDED_METHODS.has(method);
    byId("dbscenario-editor-get-panel").hidden = sql || insert || unchanged || method !== "GET";
    const mutation = influx && !sql && !insert && !unchanged && MUTATING_METHODS.has(method);
    byId("dbscenario-editor-influx-mutation").hidden = !mutation;
    byId("dbscenario-editor-influx-fixture-panel").hidden = !byId("dbscenario-editor-influx-fixture").checked;
    byId("dbscenario-editor-influx-seeds-panel").hidden = byId("dbscenario-editor-influx-action").value === "insert";
    byId("dbscenario-editor-influx-delete-body-field").hidden = !mutation || method !== "DELETE";
    byId("dbscenario-editor-add-scenario").disabled = false;
    byId("dbscenario-editor-post-cleanup").hidden = influx || method !== "POST";
    byId("dbscenario-editor-post-row-id").hidden = influx || method !== "POST";
    byId("dbscenario-editor-write-status").closest(".form-field").hidden = influx;
    for (const input of byId("dbscenario-editor-write-mappings").querySelectorAll('input[aria-label="保存後の照合に使う"]')) {
      input.disabled = influx;
      input.title = influx ? "InfluxDBは上のポイント時刻と全タグで対象を指定します" : "";
    }
    // Seed references are not available in the no-change mode.
    for (const checkbox of byId("dbscenario-editor-path-param-rows").querySelectorAll("input[data-auto-path-param]")) {
      if ((sql || unchanged || influx) && checkbox.checked) { checkbox.checked = false; checkbox.dispatchEvent(new window.Event("change")); }
      checkbox.disabled = sql || unchanged || influx;
    }
    if (unchanged || sql) {
      for (const input of byId("dbscenario-editor-query-param-rows").querySelectorAll("input")) input.disabled = false;
      byId("dbscenario-editor-guidance").textContent = "実行前後のDBを比較します。送る値と期待statusを仕様に従って入力してください。DB列やエラー条件は推測しません。";
    } else {
      byId("dbscenario-editor-guidance").textContent = byId("dbscenario-editor-guidance").dataset.mappingGuidance || "API操作を選択してください";
      syncMappedQueryParams();
    }
    if (sql) byId("dbscenario-editor-guidance").textContent = "SQLで期待値を取得し、設定した項目・配列を照合します。検索ルールは人が指定してください。";
    if (mutation) byId("dbscenario-editor-guidance").textContent = "InfluxDBの対象時刻・全タグ・期待する変更を指定してください。保存は事前なし、更新・削除は既存ポイントが必要です。";
  }

  function currentForm() {
    if (byId("dbscenario-editor-mode").value === "sql_response") return {
      mode: "sql_response", engine: byId("dbscenario-editor-engine").value,
      operation: selectedOperation(), name: byId("dbscenario-editor-name").value,
      pathParams: collectPathParams(), queryParams: collectQueryParams(), ...sqlEditor.collect(),
    };
    if (byId("dbscenario-editor-mode").value === "insert_rows") return {
      mode: "insert_rows", engine: byId("dbscenario-editor-engine").value,
      operation: selectedOperation(), name: byId("dbscenario-editor-name").value,
      table: byId("dbscenario-editor-table").value, pathParams: collectPathParams(), queryParams: collectQueryParams(),
      ...insertEditor.collect(),
    };
    if (byId("dbscenario-editor-mode").value === "unchanged") {
      return {
        mode: "unchanged", engine: byId("dbscenario-editor-engine").value,
        timeStart: byId("dbscenario-editor-time-start").value.trim(), timeEnd: byId("dbscenario-editor-time-end").value.trim(),
        operation: selectedOperation(), name: byId("dbscenario-editor-name").value,
        table: byId("dbscenario-editor-table").value, pathParams: collectPathParams(), queryParams: collectQueryParams(),
        requestBody: parseJson(byId("dbscenario-editor-unchanged-body").value || "{}", "送信するJSON body"),
        unchangedStatus: byId("dbscenario-editor-unchanged-status").value,
        unchangedColumns: byId("dbscenario-editor-unchanged-columns").value,
        unchangedWhere: parseJson(byId("dbscenario-editor-unchanged-where").value || "{}", "比較する行の条件"),
      };
    }
    const operation = selectedOperation();
    const method = operation?.method;
    let requestBody = {};
    if (method === "GET") {
      for (const row of byId("dbscenario-editor-read-filters").querySelectorAll('tr[data-parameter-source="body"]')) {
        const input = row.querySelector('input[data-request-value]');
        if (input?.value.trim()) {
          const name = row.dataset.parameterName;
          const value = parseScalar(input.value, name);
          validateBodyValue(value, operation.requestSchema?.properties?.[name] || {}, name);
          requestBody[name] = value;
        }
      }
      for (const name of operation.requestSchema?.required || []) {
        if (!Object.hasOwn(requestBody, name)) throw new Error(`必須Body「${name}」の送信値を入力してください`);
      }
    }
    if (MUTATING_METHODS.has(method) && method !== "DELETE") {
      requestBody = byId("dbscenario-editor-request-body-field").hidden
        ? collectRequestBodyFromFields()
        : parseJson(byId("dbscenario-editor-request-body").value || "{}", "リクエストbody", false);
    }
    if (method === "DELETE" && byId("dbscenario-editor-engine").value === "influxdb") {
      requestBody = parseJson(byId("dbscenario-editor-influx-delete-body").value || "{}", "リクエストbody", false);
    }
    const seedFields = SEEDED_METHODS.has(method)
      ? parseJson(byId("dbscenario-editor-seed-fields").value || "{}", "事前データ")
      : {};
    const readMappings = [...byId("dbscenario-editor-read-mappings").querySelectorAll("tr[data-response-path]")]
      .map((row) => ({
        source: row.querySelector("input[data-db-column]").value,
        target: row.dataset.responsePath,
      }))
      .filter((item) => item.source.trim());
    const readFilters = [...byId("dbscenario-editor-read-filters").querySelectorAll("tr")].map((row) => {
      const columnInput = row.querySelector("input[data-db-column]");
      const operatorSelect = row.querySelector("select");
      return {
        source: row.dataset.parameterSource || "",
        parameter: row.dataset.parameterName || "",
        column: columnInput?.value || "",
        operator: operatorSelect?.value || "",
        format: row.dataset.parameterFormat || null,
        group: row.querySelector('select[data-or-group]')?.value || null,
        ...(row.querySelector("[data-lookup-enabled]")?.checked ? {
          lookup: Object.fromEntries([...row.querySelectorAll("[data-lookup-field]")].map((input) => [input.dataset.lookupField, input.value.trim()])),
        } : {}),
      };
    }).filter((item) => item.parameter && item.column.trim());
    return {
      operation,
      engine: byId("dbscenario-editor-engine").value,
      influxAction: byId("dbscenario-editor-influx-action").value,
      influxStatus: byId("dbscenario-editor-influx-status").value,
      influxTime: byId("dbscenario-editor-influx-time").value,
      influxTags: byId("dbscenario-editor-engine").value === "influxdb" && MUTATING_METHODS.has(method)
        ? parseJson(byId("dbscenario-editor-influx-tags").value || "{}", "全タグ") : {},
      influxFields: byId("dbscenario-editor-engine").value === "influxdb" && ["POST", "PUT", "PATCH"].includes(method)
        ? collectWriteMappings(requestBody).columns : {},
      influxPreserve: byId("dbscenario-editor-influx-preserve").checked,
      influxFixture: byId("dbscenario-editor-influx-fixture").checked,
      influxSeedFields: byId("dbscenario-editor-engine").value === "influxdb" && MUTATING_METHODS.has(method) ? collectInfluxSeeds() : {},
      name: byId("dbscenario-editor-name").value,
      table: byId("dbscenario-editor-table").value,
      pathParams: collectPathParams(),
      queryParams: collectQueryParams(),
      writeStatus: byId("dbscenario-editor-write-status").value,
      requestBody,
      expandCombinations: byId("dbscenario-editor-expand-combinations").checked,
      seedFields,
      primaryKey: byId("dbscenario-editor-primary-key").value,
      responseStatus: byId("dbscenario-editor-response-status").value,
      responseShape: byId("dbscenario-editor-response-shape").value,
      responseArrayPath: byId("dbscenario-editor-response-array-path").value,
      readMappings,
      readFilters,
      responseValues: [...byId("dbscenario-editor-response-values").querySelectorAll("tr[data-value-path]")]
        .map((row) => ({ path: row.dataset.valuePath, mode: row.querySelector("[data-value-mode]").value,
          parameter: row.querySelector("[data-value-parameter]").value, fixed: row.querySelector("[data-value-fixed]").value })),
      softDelete: byId("dbscenario-editor-soft-delete").checked,
      softDeleteColumn: byId("dbscenario-editor-soft-delete-column").value,
      softDeleteValue: byId("dbscenario-editor-soft-delete-value").value,
      postCleanup: byId("dbscenario-editor-post-cleanup-enabled").checked,
      postCleanupPrimaryKey: byId("dbscenario-editor-post-cleanup-primary-key").value,
      responseRowPath: byId("dbscenario-editor-response-row-path").value,
      responseRowColumn: byId("dbscenario-editor-response-row-column").value,
    };
  }

  function renderScenarioList() {
    const list = byId("dbscenario-editor-scenario-list");
    list.replaceChildren();
    if (!scenarios.length) {
      list.append(make("p", "field-caption", "対応設定はまだありません。上のフォームからAPI操作ごとに追加してください。"));
      return;
    }
    list.append(make("strong", "", `登録済みの対応設定: ${scenarios.length}件`));
    scenarios.forEach((scenario, index) => {
      const item = make("div", "db-scenario-editor-list-item");
      const content = make("div", "db-scenario-editor-list-content");
      content.append(make("span", "", `${scenario.name} — ${scenario.request.operationId}`));
      const details = make("details", "db-scenario-editor-preview");
      details.append(make("summary", "", "自動生成される確認内容（詳細）"));
      details.append(make("pre", "", JSON.stringify(scenario, null, 2)));
      content.append(details);
      content.append(templateControls(scenario, operations, (items) => {
        scenarios.push(...items); renderScenarioList(); setStatus(`${items.length}件を追加しました。送信値・主キー・期待結果を確認して保存してください。`, "ok");
      }, (replacement) => {
        scenarios[index] = replacement; renderScenarioList(); setStatus("設定を変更しました。再保存・再レビューが必要です。", "ok");
      }, (message) => setStatus(message, "error")));
      const remove = make("button", "secondary", "削除");
      remove.type = "button";
      remove.addEventListener("click", () => {
        scenarios.splice(index, 1);
        renderScenarioList();
      });
      item.append(content, remove);
      list.append(item);
    });
  }

  byId("dbscenario-editor-operation").addEventListener("change", renderForOperation);
  byId("dbscenario-editor-mode").addEventListener("change", updateMode);
  byId("dbscenario-editor-engine").addEventListener("change", updateMode);
  byId("dbscenario-editor-influx-fixture").addEventListener("change", updateMode);
  byId("dbscenario-editor-influx-action").addEventListener("change", updateMode);
  byId("dbscenario-editor-influx-add-seed").addEventListener("click", addInfluxSeed);
  byId("dbscenario-editor-primary-key").addEventListener("change", () => {
    const operation = selectedOperation();
    if (operation) renderPathParams(operation);
  });
  byId("dbscenario-editor-soft-delete").addEventListener("change", () => {
    byId("dbscenario-editor-soft-delete-fields").hidden = !byId("dbscenario-editor-soft-delete").checked;
  });
  byId("dbscenario-editor-post-cleanup-enabled").addEventListener("change", () => {
    byId("dbscenario-editor-post-cleanup-fields").hidden = !byId("dbscenario-editor-post-cleanup-enabled").checked;
  });
  byId("dbscenario-editor-response-shape").addEventListener("change", () => {
    byId("dbscenario-editor-response-array-path-field").hidden = byId("dbscenario-editor-response-shape").value !== "array";
    const operation = selectedOperation();
    if (operation) { renderReadMappings(operation); renderResponseValues(operation); }
  });
  byId("dbscenario-editor-response-array-path").addEventListener("change", () => {
    const operation = selectedOperation();
    if (operation) { renderReadMappings(operation); renderResponseValues(operation); }
  });
  byId("dbscenario-editor-add-scenario").addEventListener("click", () => {
    try {
      const generated = buildDbScenarios(currentForm());
      for (const scenario of generated) {
        if (scenarios.some((item) => item.name === scenario.name)) throw new Error(`試験名「${scenario.name}」はすでに登録されています`);
      }
      scenarios.push(...generated);
      renderScenarioList();
      setStatus(`${generated.length}件の対応を追加しました。保存すると、この設定から実行内容を自動で作ります。`, "ok");
    } catch (error) {
      setStatus(error.message || String(error), "error");
    }
  });
  byId("dbscenario-editor-save").addEventListener("click", async () => {
    if (!scenarios.length) {
      setStatus("保存する対応設定がありません。先にAPI操作の設定を追加してください。", "error");
      return;
    }
    try {
      const currentPath = byId("dbscenario-path").value.trim();
      const separator = Math.max(currentPath.lastIndexOf("/"), currentPath.lastIndexOf("\\"));
      const defaultPath = separator >= 0 ? `${currentPath.slice(0, separator + 1)}db-checks.yaml` : "db-checks.yaml";
      const path = await saveDialog({
        defaultPath,
        filters: [{ name: "YAML", extensions: ["yaml", "yml"] }],
      });
      if (!path) return;
      const written = await invoke("bridge_call", {
        command: "save_db_scenario_yaml",
        args: { path, scenarios },
      });
      byId("dbscenario-path").value = written;
      await onSaved(written);
      setStatus(`${scenarios.length}件の対応設定を保存しました。下の「実行前の確認内容を作る」から内容を確認できます。`, "ok");
    } catch (error) {
      setStatus(`保存できませんでした: ${error.message || error}`, "error");
    }
  });

  const importButton = make("button", "secondary", "選択したDB確認ファイルを編集用に読み込む");
  importButton.type = "button";
  importButton.addEventListener("click", async () => {
    try {
      const path = byId("dbscenario-path").value.trim();
      if (!path) throw new Error("下のDB確認設定ファイルからファイルを選択してください");
      if (scenarios.length) throw new Error("編集中の設定があります。先に保存し、一覧を削除してから読み込んでください");
      scenarios = await invoke("bridge_call", {command:"load_db_scenario_templates", args:{path}});
      renderScenarioList(); setStatus(`${scenarios.length}件を編集用に読み込みました。`, "ok");
    } catch (error) { setStatus(error.message || String(error), "error"); }
  });
  byId("dbscenario-editor-save").before(importButton);
  renderScenarioList();
  return {
    async load(openapiPath) {
      if (!openapiPath) {
        operations = [];
        renderOperations();
        return;
      }
      try {
        operations = await invoke("bridge_call", {
          command: "list_db_scenario_operations",
          args: { path: openapiPath },
        }) || [];
        renderOperations();
        setStatus(operations.length ? "OpenAPIの操作を読み込みました。" : "OpenAPIから操作を取得できませんでした", operations.length ? "" : "error");
      } catch (error) {
        operations = [];
        renderOperations();
        setStatus(`API操作を読み込めませんでした: ${error.message || error}`, "error");
      }
    },
  };
}
