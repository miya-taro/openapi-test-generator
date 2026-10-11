export function addErrorDbScope(container, scope = {}) {
  const row = document.createElement("div");
  row.className = "error-db-scope";
  const engineLabel = document.createElement("label"); engineLabel.textContent = "DBの種類";
  const engine = document.createElement("select"); engine.dataset.key = "engine";
  for (const [value, label] of [["postgres", "PostgreSQL"], ["influxdb", "InfluxDB 1.x"]]) {
    const option = document.createElement("option"); option.value = value; option.textContent = label; engine.append(option);
  }
  engine.value = scope.engine || "postgres"; engineLabel.append(engine); row.append(engineLabel);
  for (const [key, label, value] of [
    ["table", "対象テーブル / measurement", scope.table || ""],
    ["columns", "比較する項目（主キー、InfluxDBはtimeと全タグも含める）", (scope.columns || []).join(", ")],
    ["where", "行条件（JSON・等値のAND）", JSON.stringify(scope.where || {})],
    ["time_start", "期間開始（含む・タイムゾーン付き）", scope.time_start || ""],
    ["time_end", "期間終了（含む・タイムゾーン付き）", scope.time_end || ""],
  ]) {
    const wrapper = document.createElement("label"); wrapper.textContent = label;
    const input = document.createElement("input"); input.dataset.key = key; input.value = value;
    input.setAttribute("aria-label", label); wrapper.append(input); row.append(wrapper);
  }
  const update = () => { for (const key of ["time_start", "time_end"]) row.querySelector(`[data-key="${key}"]`).parentElement.hidden = engine.value !== "influxdb"; };
  engine.addEventListener("change", update); update();
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
    const influx = read("engine") === "influxdb" ? { engine: "influxdb", time_start: read("time_start"), time_end: read("time_end") } : {};
    return { ...influx, table: read("table"), columns: read("columns").split(",").map((value) => value.trim()), where };
  });
}
