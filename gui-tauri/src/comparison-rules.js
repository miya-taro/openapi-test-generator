const KEY = "x-otg-comparison-rules";
const OPS = ["<", "<=", ">", ">="];

export function comparisonRulesFromSchema(schema) {
  return (schema?.[KEY] || []).map((rule) => ({ ...rule, fields: [...rule.fields] }));
}

// Preserve RFC 3339 sub-millisecond precision in comparisons.
function instant(value) {
  const text = String(value);
  const fraction = text.match(/\.(\d+)/)?.[1] || "";
  const seconds = Date.parse(text.replace(/\.\d+/, ""));
  if (!Number.isFinite(seconds)) throw new Error("試験値はタイムゾーン付きdate-timeで入力してください");
  return [seconds, fraction.replace(/0+$/, "")];
}
function order(left, right, schema) {
  if (schema?.format !== "date-time") return Math.sign(left - right);
  const a = instant(left), b = instant(right);
  if (a[0] !== b[0]) return Math.sign(a[0] - b[0]);
  const length = Math.max(a[1].length, b[1].length);
  const af = a[1].padEnd(length, "0"), bf = b[1].padEnd(length, "0");
  return af < bf ? -1 : af > bf ? 1 : 0;
}
function accepts(value, op) {
  return ({ "<": value < 0, "<=": value <= 0, ">": value > 0, ">=": value >= 0 })[op];
}
export function validateComparisonBody(body, schema) {
  for (const rule of schema?.[KEY] || []) {
    const [left, right] = rule.fields;
    if (!Object.hasOwn(body, left) || !Object.hasOwn(body, right)) continue;
    if (!accepts(order(body[left], body[right], schema.properties[left]), rule.operator)) {
      throw new Error(`Bodyの「${left} ${rule.operator} ${right}」を満たす値を入力してください`);
    }
  }
}
export function applyComparisonRules(schema, rules) {
  if (!schema) {
    if (rules.length) throw new Error("先にリクエストbodyの項目を設定してください");
    return schema;
  }
  const used = new Set();
  for (const rule of rules) {
    const [left, right] = rule.fields;
    const fields = [schema.properties?.[left], schema.properties?.[right]];
    if (!left || !right || left === right || fields.some((s) => !s) || !OPS.includes(rule.operator)) {
      throw new Error("項目間比較には異なるbody項目と大小条件を指定してください");
    }
    if ([left, right].some((name) => used.has(name))) throw new Error("項目間比較の項目を複数の条件で重複させることはできません");
    [left, right].forEach((name) => used.add(name));
    const numeric = fields.every((s) => ["integer", "number"].includes(s.type));
    const dates = fields.every((s) => s.type === "string" && s.format === "date-time");
    if (!numeric && !dates) throw new Error("項目間比較は数値同士またはdate-time同士にしてください");
    for (const key of ["lower", "upper"]) {
      if (numeric && (typeof rule[key] !== "number" || !Number.isFinite(rule[key]))) throw new Error("大小の試験値を数値で入力してください");
      if (dates && (typeof rule[key] !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/i.test(rule[key]))) {
        throw new Error("大小の試験値をタイムゾーン付きdate-time文字列で入力してください");
      }
    }
    if (order(rule.lower, rule.upper, fields[0]) >= 0) throw new Error("小さい試験値 < 大きい試験値にしてください");
  }
  if (rules.length) schema[KEY] = rules.map((rule) => ({ ...rule, fields: [...rule.fields] }));
  else delete schema[KEY];
  return schema;
}
export function renderComparisonRules(container, rules, node) {
  container.replaceChildren();
  const names = (node?.properties || []).map((p) => p.name).filter(Boolean);
  for (const [index, rule] of rules.entries()) {
    const row = document.createElement("div");
    row.className = "row";
    for (const key of [0, "operator", 1]) {
      const select = document.createElement("select");
      select.setAttribute("aria-label", `大小条件${index + 1} ${key === "operator" ? "条件" : `項目${key + 1}`}`);
      for (const value of key === "operator" ? OPS : ["", ...names]) {
        const option = document.createElement("option");
        option.value = value; option.textContent = value || "項目を選択"; select.append(option);
      }
      select.value = key === "operator" ? rule.operator : rule.fields[key];
      select.addEventListener("change", () => { if (key === "operator") rule.operator = select.value; else rule.fields[key] = select.value; });
      row.append(select);
    }
    for (const key of ["lower", "upper"]) {
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = key === "lower" ? '小さい試験値（JSON）' : '大きい試験値（JSON）';
      input.setAttribute("aria-label", `大小条件${index + 1} ${input.placeholder}`);
      input.value = rule[key] === undefined ? "" : JSON.stringify(rule[key]);
      input.addEventListener("input", () => {
        try { rule[key] = JSON.parse(input.value); input.setCustomValidity(""); }
        catch { delete rule[key]; input.setCustomValidity("数値または引用符付きの日時を入力してください"); }
      });
      row.append(input);
    }
    const remove = document.createElement("button");
    remove.type = "button"; remove.className = "secondary"; remove.textContent = "削除";
    remove.addEventListener("click", () => { rules.splice(index, 1); renderComparisonRules(container, rules, node); });
    row.append(remove); container.append(row);
  }
}
