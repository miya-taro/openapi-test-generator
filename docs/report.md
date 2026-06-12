# openapi-test-gen 依存関係レポート

---

## 1. 集計結果

| 項目 | 数値 |
|------|------|
| 対象プロジェクトファイル数 | 24 |
| 外部パッケージノード数 | 5 |
| 合計ノード数 | 29 |
| 依存エッジ数 | 72 |
| 孤立ノード数 | **0** |
| 循環依存数 | **0** |
| 不明依存数 | **0** |

**ファイル内訳**

| レイヤ | ファイル数 | 主な役割 |
|--------|-----------|---------|
| config | 4 | pnpm-workspace.yaml, package.json, tsconfig.json, vitest.config.ts |
| shared | 3 | types.ts, logger.ts, format-samples.ts |
| pipeline | 6 | cli.ts, parser, extractor, generator, id-assigner, renderer |
| rules | 5 | common, integer, string, array, object |
| test | 5 | e2e + 4 ルール単体テスト |
| fixture | 1 | tests/e2e/fixtures/simple.openapi.json |
| external | 5 | swagger-parser, commander, pino, randexp, vitest |

**依存種別内訳**

| dependency_type | エッジ数 |
|----------------|---------|
| code-import | 51 |
| build-definition | 16 |
| config-reference | 5 |

> **注意**: `tsconfig.json` が `src/**/*` を glob で参照するため 14 本、`vitest.config.ts` が `tests/**/*.test.ts` を glob で参照するため 5 本の build-definition / config-reference エッジが生成されています。Mermaid 図（§5）ではこれらを代表エッジに簡略化しています。全エッジは `dependencies.json` および `graph.html` に反映されています。

---

## 2. 形式選定理由

ノード 29 件・エッジ 72 本 → **80ファイル以下** に該当。

- **Mermaid**: レポートへの埋め込みに適しており、glob 代表エッジで簡略化した全体構造を把握するのに十分。
- **graph.html**: 全 72 エッジをインタラクティブに表示。検索・レイヤー折りたたみ・依存種別フィルタを提供。

両方を生成し、目的に応じて使い分ける。

---

## 3. 孤立ノード一覧

なし。全 29 ノードは少なくとも 1 本のエッジを持つ。

---

## 4. 循環依存一覧

なし。依存は以下の方向にのみ流れ、逆方向参照は存在しない。

```
CONFIG → PIPELINE → RULES → SHARED
TEST   → PIPELINE / RULES / SHARED
```

---

## 5. 不明依存一覧

なし。全 import は解決済み。

---

## 6. graph.html の参照方法

`docs/graph.html` をブラウザで直接開く（ファイルプロトコルで動作）。

```
# Windows
start docs\graph.html

# macOS
open docs/graph.html
```

**機能一覧**

| 機能 | 操作 |
|------|------|
| ズーム・パン | マウスホイール・ドラッグ |
| 全体表示 | 「全体表示」ボタン |
| ノード検索 | 上部検索ボックスに入力（マッチしないノードを淡色化） |
| レイヤー折りたたみ | レイヤーボタンをクリックして ON/OFF |
| 依存種別フィルタ | 依存種別ボタンをクリックして表示/非表示 |
| ノード詳細 | ノードをクリック → 右パネルに path・layer・直接依存・逆依存を表示 |
| 物理演算 | 「物理演算 OFF」ボタンでレイアウト固定 |

> `graph.html` は `dependencies.json` のデータをインライン展開して生成されています。`dependencies.json` を更新した場合は、HTML 内の `const DEPS_DATA = { ... }` ブロックを置き換えることで再生成できます。

---

## 7. Mermaid 依存グラフ（簡略版）

> `tsconfig.json` → `src/` 配下全ファイル（14 本）は `src/cli.ts` への代表エッジで表示。  
> `vitest.config.ts` → テストファイル（5 本）は `tests/e2e/generate.test.ts` への代表エッジで表示。

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
    cli["src/cli.ts"]
    par["src/parser/index.ts"]
    ext["src/extractor/index.ts"]
    gen["src/generator/index.ts"]
    ida["src/id-assigner/index.ts"]
    ren["src/renderer/json.ts"]
  end

  subgraph RULES["📋 Generator Rules"]
    gcom["rules/common.ts"]
    gint["rules/integer.ts"]
    gstr["rules/string.ts"]
    garr["rules/array.ts"]
    gobj["rules/object.ts"]
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

  %% ── 設定・ビルド（代表エッジ）
  ws     -->|build-definition| pkg
  pkg    -->|build-definition| tsc
  tsc    -->|build-definition| cli
  vitcfg -->|config-reference| te2e
  vitcfg -->|code-import|      vitest_pkg

  %% ── パイプライン
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

  %% ── ルール → 共有
  gcom -->|code-import| typ
  gint -->|code-import| typ
  gstr -->|code-import| typ
  gstr -->|code-import| smp
  gstr -->|code-import| log
  garr -->|code-import| typ
  gobj -->|code-import| typ

  %% ── 外部パッケージ
  cli  -->|code-import| cmd
  par  -->|code-import| swp
  log  -->|code-import| pino
  gstr -->|code-import| randexp

  %% ── テスト → src
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

## 8. ハブノード分析

| ノード | 被参照数 | 備考 |
|--------|---------|------|
| `src/types.ts` | 15 | 全モジュール共有の型定義中心。変更時の影響範囲最大 |
| `vitest` | 6 | テストフレームワーク全体に横断 |
| `src/logger.ts` | 5 | パイプライン全体の横断的関心事 |
| `src/types.ts`（direct） | 0 | 外向き依存ゼロ。純粋な型定義モジュール |

---

*生成日: 2026-06-12 | 対象: openapi-test-gen v0.1.0*
