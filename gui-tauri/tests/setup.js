// main.js はモジュール読み込み時点で $(id).addEventListener(...) や listen(...)、
// loadSettingsIntoForm() を即座に実行する（トップレベルの副作用）。そのため
// テストファイルが main.js を import する前に、実際の index.html の <body> を
// jsdom へ読み込み、Tauri API（invoke/listen/dialog）をモックしておく必要がある。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { vi } from "vitest";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const html = readFileSync(path.join(__dirname, "../src/index.html"), "utf-8");
const bodyMatch = html.match(/<body[^>]*>([\s\S]*)<\/body>/);
if (!bodyMatch) {
  throw new Error("index.html から <body> を抽出できませんでした");
}
// <script type="module" src="/main.js"></script> はここでは不要（テスト側でimportする）。
document.body.innerHTML = bodyMatch[1].replace(/<script[\s\S]*?<\/script>/g, "");

// invoke: コマンド名ごとに最低限つじつまが合うデフォルト応答を返す。
// 個別のテストで挙動を確認したいコマンドは、各テスト内で mockImplementation を上書きする。
export const mockInvoke = vi.fn(async (cmd) => {
  if (cmd === "load_settings") return {};
  return {};
});

export const mockOpen = vi.fn(async () => null);
export const mockSave = vi.fn(async () => null);
export const mockOpenPath = vi.fn(async () => null);

const eventHandlers = new Map();

export function emitTauriEvent(name, payload) {
  for (const handler of eventHandlers.get(name) || []) handler({ payload });
}

vi.mock("@tauri-apps/api/core", () => ({
  invoke: (...args) => mockInvoke(...args),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async (name, handler) => {
    const handlers = eventHandlers.get(name) || new Set();
    handlers.add(handler);
    eventHandlers.set(name, handlers);
    return () => handlers.delete(handler);
  }),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args) => mockOpen(...args),
  save: (...args) => mockSave(...args),
}));

vi.mock("@tauri-apps/plugin-opener", () => ({
  openPath: (...args) => mockOpenPath(...args),
}));
