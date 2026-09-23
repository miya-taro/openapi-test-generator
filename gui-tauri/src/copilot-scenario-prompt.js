import scenarioPromptDocument from "../../docs/copilot_scenario_prompt.md?raw";

const PROMPT_SECTION = "## プロンプト本体（ここから下をコピー）";

function promptBodyFromDocument(documentText) {
  const sectionStart = documentText.indexOf(PROMPT_SECTION);
  if (sectionStart < 0) throw new Error("DBシナリオ用Copilotプロンプトの見出しが見つかりません");

  const section = documentText.slice(sectionStart + PROMPT_SECTION.length);
  const match = section.match(/```\s*\r?\n([\s\S]*?)\r?\n```/);
  if (!match) throw new Error("DBシナリオ用Copilotプロンプト本文が見つかりません");
  return match[1];
}

function pathOrUnselected(path) {
  const normalized = String(path || "").replace(/[\r\n\t]+/g, " ").trim();
  return normalized || "未選択（必要ならCopilot Chatに添付してください）";
}

export function buildCopilotScenarioPrompt({
  openapiPath,
  mappingPath,
  scenarioPath,
  phpEvidencePath,
}) {
  let prompt = promptBodyFromDocument(scenarioPromptDocument)
    .replace("- OpenAPI定義: <openapi.jsonのパスを指定、またはファイルを添付>", `- OpenAPI定義: ${pathOrUnselected(openapiPath)}`)
    .replace(/- 既存のDBシナリオYAML: <[^>]*>/, `- 既存/出力予定のDBシナリオYAML: ${pathOrUnselected(scenarioPath)}`)
    .replace(/- 業務ロジックの実装: <[\s\S]*?>/, "- 業務ロジックの実装: VS Codeで開いているPHPプロジェクトのルーティング・業務ロジックを参照（未確認の情報は要確認とする）")
    .replace(/- DBスキーマ: <[^>]*>/, "- DBスキーマ: SQL・マイグレーション等のファイルが添付/参照できる場合のみ使用。CopilotがDBへ直接接続した前提にしない")
    .replace("# 厳守してほしいこと", "# GUIで選択済みの参考ファイル\n- DB対応表: " + pathOrUnselected(mappingPath)
      + "\n- PHP SQL根拠JSON: " + pathOrUnselected(phpEvidencePath)
      + "\n\n選択パスのファイルを現在のVS Codeワークスペースから参照できる場合だけ読み、内容を確認してください。直接参照できないファイルは、添付または #file で参照を求める。ファイルを読めていない場合、内容を推測で補完しない。\n\n# 厳守してほしいこと");

  return prompt;
}
