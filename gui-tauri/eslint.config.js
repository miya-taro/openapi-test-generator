// バグに直結する項目（未定義変数の参照、未使用変数、条件式の書き間違い等）に絞ったLint設定。
// フォーマット・スタイル系のルールは対象外（このプロジェクトはPrettier等を導入していないため）。
import js from "@eslint/js";

export default [
  {
    ignores: ["dist/**", "src-tauri/**", "node_modules/**"],
  },
  {
    files: ["src/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        fetch: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        FormData: "readonly",
        Blob: "readonly",
        URL: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      // 意図的に未使用の catch 変数（エラー内容を見ずに握りつぶす箇所が多数ある）を許容する
      "no-unused-vars": ["error", { caughtErrors: "none", argsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["tests/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        setTimeout: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
    },
  },
];
