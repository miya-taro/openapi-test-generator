export function addErrorDbScope(container, scope = {}) {
  const row = document.createElement("div");
  row.className = "error-db-scope";
  for (const [key, label, value] of [
    ["table", "対象テーブル", scope.table || ""],
    ["columns", "比較する列（カンマ区切り・主キーを含める）", (scope.columns || []).join(", ")],
    ["where", "行条件（JSON・等値のAND）", JSON.stringify(scope.where || {})],
  ]) {
    const wrapper = document.createElement("label"); wrapper.textContent = label;
    const input = document.createElement("input"); input.dataset.key = key; input.value = value;
    input.setAttribute("aria-label", label); wrapper.append(input); row.append(wrapper);
  }
  const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "削除";
  remove.className = "secondary"; remove.addEventListener("click", () => row.remove());
  row.append(remove); container.append(row);
}

export function collectErrorDbScopes(container) {
  return [...container.querySelectorAll(".error-db-scope")].map((row) => {
    const read = (key) => row.querySelector(`[data-key="${key}"]`).value.trim();
    let where;
    try { where = JSON.parse(read("where")); }
    catch { throw new Error("DB行条件をJSONで入力してください"); }
    return { table: read("table"), columns: read("columns").split(",").map((value) => value.trim()), where };
  });
}
