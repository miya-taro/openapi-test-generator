/**
 * GUIフォームの公開可能な設定だけを workflow/project.json に変換する。
 * パスワード・トークン・Cookie は実行時の一時設定ファイルへ分離する。
 */
export function buildProjectData({
  openapiPath,
  baseUrl,
  outputDir,
  operations = [],
  uncheckedOperations = [],
  setupSqlPath,
  teardownSqlPath,
  dbScenariosPath,
}) {
  const unchecked = new Set(uncheckedOperations);
  const project = {
    schemaVersion: 1,
    name: "API試験",
    openapiPath,
    baseUrl,
    outputDir,
    selectedOperations: operations.filter((operationId) => !unchecked.has(operationId)),
  };

  if (setupSqlPath) project.setupSqlPath = setupSqlPath;
  if (teardownSqlPath) project.teardownSqlPath = teardownSqlPath;
  if (dbScenariosPath) project.dbScenariosPath = dbScenariosPath;
  return project;
}
