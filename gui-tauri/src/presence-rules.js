const RULE_KEY = "x-otg-presence-rules";

export function presenceRulesFromSchema(schema) {
  const rules = schema?.[RULE_KEY];
  return Array.isArray(rules) ? rules.map((rule) => ({ kind: rule.kind, fields: [...(rule.fields || [])] })) : [];
}

export function applyPresenceRules(schema, rules) {
  if (!schema) {
    if (rules.length) throw new Error("先にリクエストbodyの項目を設定してください");
    return schema;
  }
  const names = new Set(Object.keys(schema.properties || {}));
  const individuallyRequired = new Set(schema.required || []);
  const seen = new Set();
  for (const rule of rules) {
    const [first, second] = rule.fields;
    if (!["atLeastOne", "together"].includes(rule.kind) || !names.has(first) || !names.has(second) || first === second) {
      throw new Error("必須条件には異なるbody項目を2つ選んでください");
    }
    if (individuallyRequired.has(first) || individuallyRequired.has(second)) {
      throw new Error("条件付き必須の項目は、項目側の「必須」を外してください");
    }
    const key = `${rule.kind}:${[first, second].sort().join(":")}`;
    if (seen.has(key)) throw new Error("同じ必須条件が重複しています");
    seen.add(key);
  }
  if (rules.length) schema[RULE_KEY] = rules;
  else delete schema[RULE_KEY];
  return schema;
}

export function renderPresenceRules(container, rules, schemaNode) {
  container.replaceChildren();
  const names = (schemaNode?.properties || []).map((property) => property.name).filter(Boolean);
  for (const [index, rule] of rules.entries()) {
    const row = document.createElement("div");
    row.className = "row";
    const select = (choices, value, label, update) => {
      const element = document.createElement("select");
      element.setAttribute("aria-label", label);
      for (const [key, text] of choices) {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = text;
        element.append(option);
      }
      element.value = value;
      element.addEventListener("change", () => update(element.value));
      return element;
    };
    row.append(select([["atLeastOne", "どちらか必須"], ["together", "両方指定または両方省略"]], rule.kind,
      "必須条件", (value) => { rule.kind = value; }));
    for (let fieldIndex = 0; fieldIndex < 2; fieldIndex++) {
      row.append(select([["", "項目を選択"], ...names.map((name) => [name, name])], rule.fields[fieldIndex] || "",
        `条件${index + 1}の項目${fieldIndex + 1}`, (value) => { rule.fields[fieldIndex] = value; }));
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary";
    remove.textContent = "削除";
    remove.addEventListener("click", () => { rules.splice(index, 1); renderPresenceRules(container, rules, schemaNode); });
    row.append(remove);
    container.append(row);
  }
}
