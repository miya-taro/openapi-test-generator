# プロジェクト依存関係グラフ

## 集計結果

| 項目 | 数値 |
|------|------|
| 対象プロジェクトファイル数 | 24 |
| 外部パッケージノード数 | 5 |
| 合計ノード数 | 29 |
| 依存エッジ数 | 55 |
| 孤立ノード | **0** |
| 循環依存 | **0** |
| 不明依存 | **0** |

**ファイル内訳**

| レイヤ | ファイル数 |
|--------|-----------|
| 実装 TS（src/） | 14 |
| テスト TS（tests/） | 5 |
| 設定・ビルド | 4 |
| フィクスチャ JSON | 1 |
| 外部パッケージ | 5 |

---

## 形式選定理由

ノード 29 件・エッジ 55 本 → **80ファイル以下** に該当。  
Mermaid 1枚で収まるが、エッジが集中する `src/types.ts` と `src/logger.ts` の視認性を高めるため **サブグラフでクラスタ分割** した単一図を採用。

---

## Mermaid 依存グラフ

```mermaid
graph LR

  subgraph CONFIG["⚙️ 設定・ビルド"]
    ws["pnpm-workspace.yaml"]
    pkg["package.json"]
    tsc["tsconfig.json"]
    vitcfg["vitest.config.ts"]
  end

  subgraph SHARED["🔧 共有モジュール"]
    typ["src/types.ts"]
    log["src/logger.ts"]
    smp["src/samples/format-samples.ts"]
  end

  subgraph PIPELINE["🚀 パイプライン（Phase 1〜5）"]
    cli["src/cli.ts\n[エントリポイント]"]
    par["src/parser/index.ts\n[Phase1: Parse]"]
    ext["src/extractor/index.ts\n[Phase2: Extract]"]
    gen["src/generator/index.ts\n[Phase3: Generate]"]
    ida["src/id-assigner/index.ts\n[Phase4: ID Assign]"]
    ren["src/renderer/json.ts\n[Phase5: Render]"]
  end

  subgraph RULES["📋 Generator Rules"]
    gcom["rules/common.ts\n[required/type]"]
    gint["rules/integer.ts\n[integer/number]"]
    gstr["rules/string.ts\n[string]"]
    garr["rules/array.ts\n[array]"]
    gobj["rules/object.ts\n[object]"]
  end

  subgraph EXTPKG["📦 外部パッケージ"]
    swp["@apidevtools/swagger-parser"]
    cmd["commander"]
    pino["pino"]
    randexp["randexp"]
    vitest_pkg["vitest"]
  end

  subgraph TESTS["🧪 テスト"]
    te2e["e2e/generate.test.ts"]
    tcom["rules/common.test.ts"]
    tint["rules/integer.test.ts"]
    tstr["rules/string.test.ts"]
    tarr["rules/array.test.ts"]
    fix[["fixtures/simple.openapi.json"]]
  end

  %% ── 設定・ビルド ──────────────────────────────
  ws     -->|build-definition| pkg
  pkg    -->|build-definition| tsc
  tsc    -->|build-definition| cli
  vitcfg -->|config-reference| te2e
  vitcfg -->|code-import|      vitest_pkg

  %% ── パイプライン内 code-import ────────────────
  cli -->|code-import| par
  cli -->|code-import| ext
  cli -->|code-import| gen
  cli -->|code-import| ida
  cli -->|code-import| ren
  cli -->|code-import| typ
  cli -->|code-import| log

  par -->|code-import| log

  ext -->|code-import| par
  ext -->|code-import| typ
  ext -->|code-import| log

  gen -->|code-import| typ
  gen -->|code-import| gcom
  gen -->|code-import| gint
  gen -->|code-import| gstr
  gen -->|code-import| garr
  gen -->|code-import| gobj

  ida -->|code-import| typ
  ida -->|code-import| log

  ren -->|code-import| typ

  %% ── ルール → 共有 ─────────────────────────────
  gcom -->|code-import| typ
  gint -->|code-import| typ
  gstr -->|code-import| typ
  gstr -->|code-import| smp
  gstr -->|code-import| log
  garr -->|code-import| typ
  gobj -->|code-import| typ

  %% ── 外部パッケージ ────────────────────────────
  cli  -->|code-import| cmd
  par  -->|code-import| swp
  log  -->|code-import| pino
  gstr -->|code-import| randexp

  %% ── テスト → src ──────────────────────────────
  te2e -->|code-import|      par
  te2e -->|code-import|      ext
  te2e -->|code-import|      gen
  te2e -->|code-import|      ida
  te2e -->|code-import|      typ
  te2e -->|config-reference| fix
  te2e -->|code-import|      vitest_pkg

  tcom -->|code-import| gcom
  tcom -->|code-import| typ
  tcom -->|code-import| vitest_pkg

  tint -->|code-import| gint
  tint -->|code-import| typ
  tint -->|code-import| vitest_pkg

  tstr -->|code-import| gstr
  tstr -->|code-import| typ
  tstr -->|code-import| vitest_pkg

  tarr -->|code-import| garr
  tarr -->|code-import| typ
  tarr -->|code-import| vitest_pkg
```

---

## 注目ポイント

**ハブノード（被参照数トップ）**

| ノード | 被参照数 | 理由 |
|--------|---------|------|
| `src/types.ts` | 13 | 全モジュールが共有する型定義の中心 |
| `src/logger.ts` | 6 | パイプライン全体に横断する横断的関心事 |
| `vitest` | 6 | テストフレームワーク本体 |

**依存が一方向に流れるクリーンな構造**  
`CONFIG → PIPELINE → RULES → SHARED` の方向に依存が流れており、逆方向参照なし。循環依存ゼロを確認。

**孤立ノードなし**  
`src/samples/format-samples.ts` は `rules/string.ts` からのみ参照、`fixtures/simple.openapi.json` は `e2e/generate.test.ts` からのみ参照されており、いずれもグラフに接続済み。
