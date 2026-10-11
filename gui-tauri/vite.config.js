import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

// Tauri公式ドキュメントの推奨設定に準拠。
// https://tauri.app/start/frontend/vanillajs/

export default defineConfig(async () => ({
  root: "src",
  publicDir: "assets",

  // Tauriのdevサーバーがこのポートに固定で接続しにくるため、必ず空けておく必要がある。
  server: {
    port: 1420,
    strictPort: true,
    fs: {
      allow: [
        fileURLToPath(new URL("./src/", import.meta.url)),
        fileURLToPath(new URL("../docs/", import.meta.url)),
      ],
    },
    watch: {
      // src-tauri側の変更でフロントエンドを再読み込みしない。
      ignored: ["**/src-tauri/**"],
    },
  },

  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
}));
