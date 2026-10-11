import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { listen as tauriListen } from "@tauri-apps/api/event";
import { open as tauriOpen, save as tauriSave } from "@tauri-apps/plugin-dialog";
import { openPath as tauriOpenPath } from "@tauri-apps/plugin-opener";

const isDesktop = Boolean(window.__TAURI_INTERNALS__);
let webTokenPromise;
let webEvents;
const eventListeners = new Map();
const savedPaths = new Set();
const savedHandles = new Map();

function addBrowserNotice() {
  if (isDesktop) return;
  const mainArea = document.getElementById("main-area");
  if (!mainArea) return;
  const notice = document.createElement("div");
  notice.className = "banner info browser-mode-notice";
  notice.textContent = "ブラウザー版です。選択したファイルはこのPCのアプリ用フォルダーへコピーされます。結果を開くとファイルがダウンロードされます。";
  mainArea.prepend(notice);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", addBrowserNotice, { once: true });
} else {
  addBrowserNotice();
}

async function webToken() {
  if (!webTokenPromise) {
    webTokenPromise = fetch("/api/client-config", { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "ローカルサーバーに接続できません");
        return body.token;
      });
  }
  return webTokenPromise;
}

async function post(path, payload) {
  const token = await webToken();
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OpenApi-Token": token },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `ローカル処理に失敗しました (${response.status})`);
  return body;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename || "download";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function saveBlob(path, blob, filename) {
  const handle = savedHandles.get(path);
  savedPaths.delete(path);
  savedHandles.delete(path);
  if (handle) {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return;
  }
  downloadBlob(blob, filename);
}

export async function invoke(command, args = {}) {
  if (isDesktop) return tauriInvoke(command, args);
  const { result } = await post("/api/invoke", { command, args });
  if (command === "write_config_file" && args.path && savedPaths.has(args.path)) {
    await saveBlob(
      args.path,
      new Blob([JSON.stringify(args.data, null, 2)], { type: "application/json" }),
      args.path.split(/[\\/]/).pop(),
    );
  }
  if (command === "bridge_call" && args.command === "save_operation_body_contract") {
    const path = args.args?.destination_path;
    if (path && savedPaths.has(path)) {
      await openPath(path);
    }
  }
  return result;
}

function openEventSource() {
  if (webEvents) return webEvents;
  webEvents = webToken().then((token) => new Promise((resolve, reject) => {
    const source = new window.EventSource("/api/events?token=" + encodeURIComponent(token));
    for (const eventName of ["proc-line", "proc-done"]) {
      source.addEventListener(eventName, (event) => {
        let payload;
        try { payload = JSON.parse(event.data); } catch { return; }
        for (const listener of eventListeners.get(eventName) || []) listener({ payload });
      });
    }
    source.addEventListener("open", () => resolve(source), { once: true });
    source.addEventListener("error", () => {
      if (source.readyState === window.EventSource.CLOSED) {
        webEvents = null;
        reject(new Error("実行ログの接続が切れました"));
      }
    });
  }));
  return webEvents;
}

export async function listen(eventName, callback) {
  if (isDesktop) return tauriListen(eventName, callback);
  if (!eventListeners.has(eventName)) eventListeners.set(eventName, new Set());
  const listeners = eventListeners.get(eventName);
  listeners.add(callback);
  await openEventSource();
  return () => {
    listeners.delete(callback);
    if (!listeners.size) eventListeners.delete(eventName);
    if (!eventListeners.size && webEvents) {
      webEvents.then((source) => source.close());
      webEvents = null;
    }
  };
}

function acceptFor(filters = []) {
  return filters.flatMap((filter) => filter.extensions || [])
    .map((extension) => `.${String(extension).replace(/^\./, "")}`)
    .join(",");
}

function chooseFile(options = {}) {
  if (options.directory) {
    const folderName = window.prompt("出力先フォルダー名を入力してください（保存先はアプリ用フォルダー内です）", "output");
    if (!folderName) return Promise.resolve(null);
    return post("/api/directory", { name: folderName }).then(({ path }) => path);
  }
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = acceptFor(options.filters);
    input.multiple = Boolean(options.multiple);
    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      input.remove();
      if (!files.length) { resolve(null); return; }
      try {
        const paths = await Promise.all(files.map(async (file) => {
          const token = await webToken();
          const response = await fetch(`/api/upload?name=${encodeURIComponent(file.name)}`, {
            method: "POST",
            headers: { "X-OpenApi-Token": token, "Content-Type": "application/octet-stream" },
            body: file,
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || "ファイルを読み込めませんでした");
          return result.path;
        }));
        resolve(options.multiple ? paths : paths[0]);
      } catch (error) { reject(error); }
    }, { once: true });
    input.addEventListener("cancel", () => { input.remove(); resolve(null); }, { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

export async function open(options = {}) {
  if (isDesktop) return tauriOpen(options);
  return chooseFile(options);
}

export async function save(options = {}) {
  if (isDesktop) return tauriSave(options);
  let handle = null;
  if (window.showSaveFilePicker) {
    try {
      const extensions = acceptFor(options.filters).split(",").filter(Boolean);
      handle = await window.showSaveFilePicker({
        suggestedName: options.defaultPath || "config.json",
        types: extensions.length
          ? [{ description: options.filters?.[0]?.name || "ファイル", accept: { "application/octet-stream": extensions } }]
          : undefined,
      });
    } catch (error) {
      if (error.name === "AbortError") return null;
      throw error;
    }
  }
  const { path } = await post("/api/save-path", { defaultPath: handle?.name || options.defaultPath || "config.json" });
  savedPaths.add(path);
  if (handle) savedHandles.set(path, handle);
  return path;
}

export async function openPath(path) {
  if (isDesktop) return tauriOpenPath(path);
  const token = await webToken();
  const response = await fetch("/api/open-path", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OpenApi-Token": token },
    body: JSON.stringify({ path }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || "ファイルをダウンロードできませんでした");
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const filename = encodedName ? decodeURIComponent(encodedName) : path.split(/[\\/]/).pop();
  const blob = await response.blob();
  if (savedPaths.has(path)) await saveBlob(path, blob, filename);
  else downloadBlob(blob, filename);
}
