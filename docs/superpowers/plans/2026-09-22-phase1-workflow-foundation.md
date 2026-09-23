# Phase 1 Workflow Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存の OpenAPI Layer 1 と DB シナリオを、安定したプロジェクト設定・成果物規約・統一進捗イベントを介して Tauri GUI から実行できる土台を構築する。

**Architecture:** 新しい `workflow/` Python パッケージが既存 `src/`・`runner/` の CLI を包み、GUI へ JSON Lines の統一イベントを返す。Tauri の既存 `run_script`・`cancel_script` はプロセス境界として維持し、フロントエンドは `workflow-client.js` だけを通してワークフローを起動する。

**Tech Stack:** Python 3.10+、dataclasses、JSON、subprocess、Tauri 2、Rust、Vanilla JavaScript、Vitest、pytest

**Spec:** `docs/superpowers/specs/2026-09-22-local-api-test-automation-design.md`

## Global Constraints

- GitHub への接続を必要としないこと。
- 正式 GUI は `gui-tauri/` とし、新機能を CLI 専用にしないこと。
- `src/` と `runner/` の公開 CLI は既存利用者のため維持すること。
- パスワード、トークン、Cookie をプロジェクト設定やログへ保存しないこと。
- 通常画面では OpenAPI、Base URL、出力先だけを主要入力として表示すること。
- 内部例外は詳細ログへ残し、GUI の主要メッセージは利用者が取るべき行動を日本語で示すこと。
- 既存 Excel、JSON、JUnit XML、DB シナリオの出力互換性を維持すること。
- Python 3.10 以降と Windows を初期対象とすること。

---

## File Structure

### 新規ファイル

- `workflow/__init__.py`: パッケージ境界とバージョン
- `workflow/models.py`: プロジェクト設定、実行要求、成果物の型
- `workflow/project_store.py`: `project.json` の読込・保存・パス解決
- `workflow/events.py`: JSON Lines イベントの型と出力
- `workflow/commands.py`: 既存 CLI に渡す安全な引数配列の構築
- `workflow/executor.py`: 子プロセス実行、進捗変換、終了結果
- `workflow/cli.py`: GUI が呼ぶ単一エントリーポイント
- `workflow/tests/`: 上記モジュールの pytest
- `gui-tauri/src/workflow-client.js`: Tauri IPC と統一イベントを扱うフロントエンド境界
- `gui-tauri/tests/workflow-client.test.js`: IPC・イベント・キャンセルの Vitest
- `scripts/verify-local.ps1`: GitHub Actions に依存しない一括検証

### 変更ファイル

- `gui-tauri/src/index.html`: 工程ナビゲーションと基本入力
- `gui-tauri/src/main.js`: 画面状態と DOM 操作へ責務を縮小
- `gui-tauri/src/styles.css`: 工程表示、詳細設定、結果カード
- `gui-tauri/src-tauri/tauri.conf.json`: `workflow/` を配布リソースへ追加
- `gui-tauri/src-tauri/src/lib.rs`: スクリプト許可範囲と Python 診断
- `gui-tauri/tests/main.test.js`: 新しい主要導線
- `README.md`: 新 GUI 導線とローカル検証
- `gui-tauri/README.md`: 開発・ビルド・診断

## Interfaces

### `workflow.models.ProjectConfig`

```python
@dataclass(frozen=True)
class ProjectConfig:
    schema_version: int
    name: str
    project_dir: Path
    openapi_path: Path
    base_url: str
    output_dir: Path
    selected_operations: tuple[str, ...] = ()
    setup_sql_path: Path | None = None
    teardown_sql_path: Path | None = None
    db_scenarios_path: Path | None = None
```

秘密値は含めない。DB と認証の秘密値は実行時の一時設定ファイルで渡す。

### `workflow.models.RunRequest`

```python
@dataclass(frozen=True)
class RunRequest:
    workflow: Literal["contract", "db-scenarios"]
    project_file: Path
    runtime_config_path: Path | None = None
    auth_config_path: Path | None = None
    parallel: int = 1
    fail_fast: bool = False
    persist_cookies: bool = False
```

### JSON Lines event

```json
{"type":"stage_started","stage":"generate","message":"試験仕様を生成しています"}
{"type":"progress","stage":"execute","current":12,"total":71,"message":"12 / 71"}
{"type":"artifact","kind":"result_excel","path":"C:\\work\\artifacts\\result.xlsx"}
{"type":"stage_finished","stage":"execute","status":"passed","exit_code":0}
{"type":"workflow_finished","status":"passed","exit_code":0}
```

`type` は `stage_started`、`log`、`progress`、`artifact`、`stage_finished`、`workflow_finished` のいずれかとする。JSON 以外の子プロセス出力は `log` イベントの `message` に格納する。

---

### Task 1: プロジェクト設定モデルと保存形式

**Files:**
- Create: `workflow/__init__.py`
- Create: `workflow/models.py`
- Create: `workflow/project_store.py`
- Create: `workflow/tests/__init__.py`
- Create: `workflow/tests/test_project_store.py`

**Interfaces:**
- Produces: `ProjectConfig`, `ProjectConfigError`, `load_project(path: Path) -> ProjectConfig`, `save_project(config: ProjectConfig, path: Path) -> None`
- Consumes: 標準ライブラリのみ

- [ ] **Step 1: 相対パス解決と秘密値拒否の失敗テストを書く**

```python
def test_load_project_resolves_paths_from_project_file(tmp_path):
    project = tmp_path / "sample"
    project.mkdir()
    (project / "openapi.json").write_text('{"openapi":"3.0.3","paths":{}}', encoding="utf-8")
    path = project / "project.json"
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "name": "sample",
        "openapiPath": "openapi.json",
        "baseUrl": "http://vm.local/api",
        "outputDir": "artifacts"
    }), encoding="utf-8")

    config = load_project(path)

    assert config.project_dir == project.resolve()
    assert config.openapi_path == (project / "openapi.json").resolve()
    assert config.output_dir == (project / "artifacts").resolve()


@pytest.mark.parametrize("secret_key", ["password", "token", "cookie", "authorization"])
def test_load_project_rejects_secret_keys(tmp_path, secret_key):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({
        "schemaVersion": 1,
        "name": "unsafe",
        "openapiPath": "openapi.json",
        "baseUrl": "http://vm.local",
        "outputDir": "artifacts",
        secret_key: "secret"
    }), encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="秘密情報"):
        load_project(path)
```

- [ ] **Step 2: テストが未実装で失敗することを確認する**

Run: `python -m pytest workflow/tests/test_project_store.py -q`  
Expected: FAIL with `ModuleNotFoundError: No module named 'workflow.project_store'`

- [ ] **Step 3: 不変 dataclass と厳格な JSON 読込を実装する**

`schemaVersion` は `1` のみ許可する。`name`、`openapiPath`、`baseUrl`、`outputDir` を必須とし、未知キーは `ProjectConfigError` にする。入力パスはプロジェクトファイルの親から解決し、保存時は可能な限り相対パスへ戻す。キー名を小文字化して `password`、`secret`、`token`、`cookie`、`authorization` を含む未知キーを秘密情報として明示的に拒否する。

- [ ] **Step 4: 保存・再読込の往復テストを追加して通す**

```python
def test_save_then_load_preserves_project_config(tmp_path):
    project_file = tmp_path / "project.json"
    config = ProjectConfig(
        schema_version=1,
        name="orders",
        project_dir=tmp_path,
        openapi_path=tmp_path / "openapi.json",
        base_url="http://vm.local/api",
        output_dir=tmp_path / "artifacts",
        selected_operations=("getOrder", "createOrder"),
    )
    save_project(config, project_file)
    assert load_project(project_file) == config
```

Run: `python -m pytest workflow/tests/test_project_store.py -q`  
Expected: PASS

- [ ] **Step 5: コミットする**

```powershell
git add workflow/__init__.py workflow/models.py workflow/project_store.py workflow/tests
git commit -m "feat: API試験プロジェクト設定モデルを追加"
```

### Task 2: 成果物規約と既存 CLI 引数ビルダー

**Files:**
- Modify: `workflow/models.py`
- Create: `workflow/commands.py`
- Create: `workflow/tests/test_commands.py`

**Interfaces:**
- Consumes: `ProjectConfig`, `RunRequest`
- Produces: `ArtifactPaths`, `artifact_paths(config: ProjectConfig) -> ArtifactPaths`, `build_generate_command(...) -> list[str]`, `build_contract_run_command(...) -> list[str]`, `build_db_scenario_command(...) -> list[str]`

- [ ] **Step 1: 成果物パスと引数配列の失敗テストを書く**

```python
def test_contract_commands_use_stable_artifact_paths(project_config, run_request):
    paths = artifact_paths(project_config)
    generate = build_generate_command(project_config, paths)
    execute = build_contract_run_command(project_config, run_request, paths)

    assert paths.spec_excel.name == "test-spec.xlsx"
    assert paths.cases_json.name == "test-cases.json"
    assert paths.result_excel.name == "test-result.xlsx"
    assert paths.junit_xml.name == "contract-junit.xml"
    assert generate[:2] == [sys.executable, str(REPO_ROOT / "src" / "cli.py")]
    assert "--excel-output" in generate
    assert execute[:2] == [sys.executable, str(REPO_ROOT / "runner" / "runner.py")]
    assert "--junit-xml" in execute
```

- [ ] **Step 2: テストが未実装で失敗することを確認する**

Run: `python -m pytest workflow/tests/test_commands.py -q`  
Expected: FAIL with import error

- [ ] **Step 3: 成果物と引数構築を実装する**

成果物は `<output_dir>/<run_id>/` へ置く。`run_id` は CLI 起動時に `YYYYMMDD-HHMMSS-<8桁hex>` で一度生成し、同じワークフロー内で共有する。コマンドは常に `list[str]` で構築し、`shell=True` と文字列連結を使用しない。

既存 CLI の次の引数だけをフェーズ 1 で公開する。

- 生成: input、`--output`、`--excel-output`、`--operations`
- Layer 1: Excel、OpenAPI、`--base-url`、`--setup`、`--teardown`、`--config`、`--auth-config`、`--parallel`、`--fail-fast`、`--cookie-jar`、`--junit-xml`
- DB: scenarios、OpenAPI、`--base-url`、`--config`、`--auth-config`、`--cookie-jar`、`--junit-xml`

- [ ] **Step 4: 引数注入と秘密値非包含のテストを追加して通す**

```python
def test_commands_never_embed_runtime_secret_values(project_config, run_request):
    command = build_contract_run_command(project_config, run_request, artifact_paths(project_config))
    joined = " ".join(command).lower()
    assert "password" not in joined
    assert "bearer " not in joined
    assert run_request.runtime_config_path.as_posix() in " ".join(command).replace("\\", "/")
```

Run: `python -m pytest workflow/tests/test_commands.py -q`  
Expected: PASS

- [ ] **Step 5: コミットする**

```powershell
git add workflow/models.py workflow/commands.py workflow/tests/test_commands.py
git commit -m "feat: ワークフロー成果物と既存CLI引数を統一"
```

### Task 3: 統一イベントと子プロセス実行

**Files:**
- Create: `workflow/events.py`
- Create: `workflow/executor.py`
- Create: `workflow/tests/test_events.py`
- Create: `workflow/tests/test_executor.py`

**Interfaces:**
- Produces: `WorkflowEvent`, `emit_event(event, stream)`, `run_command(stage, command, emit) -> StageResult`
- Consumes: Task 2 のコマンド配列

- [ ] **Step 1: JSON Lines と非 JSON ログ変換の失敗テストを書く**

```python
def test_emit_event_writes_one_utf8_json_object_per_line():
    stream = io.StringIO()
    emit_event(WorkflowEvent.log("generate", "71件生成しました"), stream)
    assert json.loads(stream.getvalue()) == {
        "type": "log", "stage": "generate", "level": "info", "message": "71件生成しました"
    }


def test_run_command_wraps_child_output_as_log_event(fake_process, emitted):
    fake_process.stdout = iter(["line 1\n", "line 2\n"])
    fake_process.returncode = 0
    result = run_command("generate", ["python", "fake.py"], emitted.append)
    assert [e.message for e in emitted if e.type == "log"] == ["line 1", "line 2"]
    assert result.status == "passed"
```

- [ ] **Step 2: テストが未実装で失敗することを確認する**

Run: `python -m pytest workflow/tests/test_events.py workflow/tests/test_executor.py -q`  
Expected: FAIL with import error

- [ ] **Step 3: イベント型と逐次読込を実装する**

`subprocess.Popen` は `shell=False`、`text=True`、`encoding="utf-8"`、`errors="replace"` を使用する。標準エラーは標準出力へ統合し、出力順を保持する。子プロセスの既存進捗文言は `workflow/executor.py` の変換関数一か所だけで `progress` へ変換する。変換できない行は失わず `log` とする。

- [ ] **Step 4: 終了コードと起動失敗テストを追加して通す**

```python
def test_run_command_reports_launch_failure_without_raw_traceback(monkeypatch, emitted):
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("python missing")))
    result = run_command("generate", ["python", "missing.py"], emitted.append)
    assert result.status == "error"
    assert result.exit_code == -1
    assert emitted[-1].type == "stage_finished"
    assert emitted[-1].message == "処理を開始できませんでした。Pythonの実行環境を確認してください。"
    assert "python missing" in emitted[-1].detail
```

Run: `python -m pytest workflow/tests/test_events.py workflow/tests/test_executor.py -q`  
Expected: PASS

- [ ] **Step 5: コミットする**

```powershell
git add workflow/events.py workflow/executor.py workflow/tests/test_events.py workflow/tests/test_executor.py
git commit -m "feat: ワークフロー進捗イベントをJSON Linesへ統一"
```

### Task 4: 契約試験・DB試験の統一ワークフロー CLI

**Files:**
- Create: `workflow/cli.py`
- Create: `workflow/tests/test_cli.py`
- Modify: `gui-tauri/src-tauri/tauri.conf.json`

**Interfaces:**
- Consumes: `load_project`, Task 2 のコマンド、`run_command`
- Produces: `python workflow/cli.py run-contract --project <path> [runtime options]` と `run-db-scenarios`

- [ ] **Step 1: 契約試験の段階順序を検証する失敗テストを書く**

```python
def test_run_contract_emits_generate_then_execute(monkeypatch, project_file, capsys):
    calls = []
    monkeypatch.setattr(cli, "run_command", lambda stage, command, emit: calls.append(stage) or StageResult.passed())
    code = cli.main(["run-contract", "--project", str(project_file)])
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 0
    assert calls == ["generate", "execute"]
    assert events[-1]["type"] == "workflow_finished"
    assert events[-1]["status"] == "passed"
```

- [ ] **Step 2: テストが未実装で失敗することを確認する**

Run: `python -m pytest workflow/tests/test_cli.py -q`  
Expected: FAIL with import error

- [ ] **Step 3: CLI と失敗時短絡を実装する**

`run-contract` は `generate` 成功後だけ `execute` を開始する。`run-db-scenarios` は `db-scenarios` 一段階を実行する。各ワークフローの最後に必ず `workflow_finished` を一回だけ出力する。終了コードは `0=成功`、`1=失敗`、`2=警告のみ`、`130=キャンセル`、`-1=起動不能` を内部契約とし、OS へ返す際の負値は `3` に正規化する。

- [ ] **Step 4: 失敗短絡と成果物イベントのテストを追加する**

```python
def test_generation_failure_does_not_execute(monkeypatch, project_file):
    calls = []
    def fake_run(stage, command, emit):
        calls.append(stage)
        return StageResult.failed(1)
    monkeypatch.setattr(cli, "run_command", fake_run)
    assert cli.main(["run-contract", "--project", str(project_file)]) == 1
    assert calls == ["generate"]
```

Run: `python -m pytest workflow/tests/test_cli.py -q`  
Expected: PASS

- [ ] **Step 5: 配布リソースへ `workflow/` を追加し、Rust設定テストを通す**

`gui-tauri/src-tauri/tauri.conf.json` の `bundle.resources` に `../../workflow`: `workflow` を追加する。

Run: `cd gui-tauri; cargo test --manifest-path src-tauri/Cargo.toml`  
Expected: PASS

- [ ] **Step 6: コミットする**

```powershell
git add workflow/cli.py workflow/tests/test_cli.py gui-tauri/src-tauri/tauri.conf.json
git commit -m "feat: 契約試験とDB試験の統一ワークフローを追加"
```

### Task 5: フロントエンドのワークフロー境界

**Files:**
- Create: `gui-tauri/src/workflow-client.js`
- Create: `gui-tauri/tests/workflow-client.test.js`
- Modify: `gui-tauri/src/main.js`

**Interfaces:**
- Consumes: Tauri `invoke("run_script")`、`proc-line`、`proc-done`
- Produces: `createWorkflowClient({ invoke, listen })`、`run(request, callbacks)`、`cancel()`

- [ ] **Step 1: JSONイベント、ログ互換、起動失敗、キャンセルの失敗テストを書く**

```javascript
it("parses workflow JSON lines and forwards typed events", async () => {
  const client = createWorkflowClient({ invoke, listen })
  const onEvent = vi.fn()
  const run = client.run({ projectPath: "C:/p/project.json", workflow: "contract" }, { onEvent })
  emitProcLine('{"type":"progress","stage":"execute","current":2,"total":5}')
  emitProcDone(0)
  await run
  expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "progress", current: 2 }))
})

it("rejects with a friendly launch error and clears active run", async () => {
  invoke.mockRejectedValueOnce(new Error("spawn failed"))
  const client = createWorkflowClient({ invoke, listen })
  await expect(client.run(request, callbacks)).rejects.toThrow("処理を開始できませんでした")
  expect(client.isRunning()).toBe(false)
})
```

- [ ] **Step 2: Vitestで未実装失敗を確認する**

Run: `cd gui-tauri; npm test -- --run tests/workflow-client.test.js`  
Expected: FAIL with module not found

- [ ] **Step 3: 状態機械を実装する**

同時に一つの実行だけを許可する。`proc-line.runId` が現在値と一致する場合だけ処理する。JSON parse に失敗した行は `{type:"log", level:"info", message: line}` として扱う。`invoke` の reject と `proc-done` の両経路で active state を解除する。キャンセルは一回だけ `cancel_script` を呼び、二重クリックを無視する。

- [ ] **Step 4: main.js の実行経路を client に置換する**

既存の生成→実行、DBシナリオ実行で直接 `invoke("run_script")`、`proc-line`、`proc-done` を扱っている箇所を削除し、`workflow-client.js` のコールバックから `feedProgress`、ログ、結果表示を更新する。DB準備用の単発生成コマンドはフェーズ 1 では既存 `runSimpleScript` を維持する。

- [ ] **Step 5: 全フロントエンドテストとLintを通す**

Run: `cd gui-tauri; npm test -- --run`  
Expected: PASS

Run: `cd gui-tauri; npm run lint`  
Expected: PASS

- [ ] **Step 6: コミットする**

```powershell
git add gui-tauri/src/workflow-client.js gui-tauri/src/main.js gui-tauri/tests/workflow-client.test.js
git commit -m "refactor: GUIの試験実行を統一ワークフローへ移行"
```

### Task 6: 工程中心の GUI とプロジェクト保存

**Files:**
- Modify: `gui-tauri/src/index.html`
- Modify: `gui-tauri/src/main.js`
- Modify: `gui-tauri/src/styles.css`
- Modify: `gui-tauri/tests/main.test.js`

**Interfaces:**
- Consumes: `workflow-client.js`、`project.json`
- Produces: 5工程ナビゲーション、基本入力、詳細設定、成果物一覧

- [ ] **Step 1: DOM構造と基本導線の失敗テストを書く**

```javascript
it("shows only the three basic inputs before advanced settings are opened", () => {
  expect(document.querySelector("#project-source")).not.toBeNull()
  expect(document.querySelector("#base-url")).not.toBeNull()
  expect(document.querySelector("#output-dir")).not.toBeNull()
  expect(document.querySelector("#advanced-settings").open).toBe(false)
})

it("moves from target setup to review only after validation succeeds", async () => {
  invoke.mockResolvedValueOnce("OK（operation数: 4）")
  await validateAndContinue()
  expect(document.querySelector('[data-step="review"]').classList).toContain("is-active")
})
```

- [ ] **Step 2: Vitestで失敗を確認する**

Run: `cd gui-tauri; npm test -- --run tests/main.test.js`  
Expected: FAIL because the new step elements do not exist

- [ ] **Step 3: 5工程のシェルを実装する**

工程は「対象を登録」「仕様を確認」「試験を確認」「実行」「結果」とする。フェーズ 1 では「仕様を確認」は OpenAPI operation 一覧、「試験を確認」は生成対象 operation と出力予定ファイルを表示する。既存のDB準備、認証、DB接続、並列数等は `<details id="advanced-settings">` 配下へ移す。

- [ ] **Step 4: project.jsonの保存・再読込を接続する**

GUI の「プロジェクトを保存」で `ProjectConfig` 互換 JSON を保存し、「プロジェクトを開く」で基本入力と operation 選択を復元する。パスワード、ログインBody、トークン、Cookieは保存しない。

- [ ] **Step 5: エラーと成果物表示を実装する**

主要エラーは「何が失敗したか」「どの入力を確認するか」「詳細ログを開く」の三点を表示する。`artifact` イベントは結果工程にファイル種別、パス、「開く」ボタンとして追加する。生の `TypeError` や Python traceback は折りたたみ詳細ログだけに表示する。

- [ ] **Step 6: アクセシビリティとレスポンシブテストを追加する**

すべての入力に `label for` を持たせ、工程ボタンに `aria-current="step"`、実行中領域に `aria-live="polite"` を設定する。幅 900px 未満では二列フォームを一列にする。

Run: `cd gui-tauri; npm test -- --run`  
Expected: PASS

Run: `cd gui-tauri; npm run lint`  
Expected: PASS

- [ ] **Step 7: コミットする**

```powershell
git add gui-tauri/src/index.html gui-tauri/src/main.js gui-tauri/src/styles.css gui-tauri/tests/main.test.js
git commit -m "feat: GUIをAPI試験の5工程に再構成"
```

### Task 7: Tauriプロセス境界と実行環境診断

**Files:**
- Modify: `gui-tauri/src-tauri/src/lib.rs`
- Modify: `gui-tauri/src/main.js`
- Modify: `gui-tauri/src/index.html`

**Interfaces:**
- Produces: `diagnose_runtime() -> RuntimeDiagnosis`
- Consumes: Python executable、同梱リソース

- [ ] **Step 1: 許可スクリプトと診断結果のRust単体テストを書く**

```rust
#[test]
fn workflow_script_is_allowed_but_parent_traversal_is_rejected() {
    assert!(validate_script_path("workflow/cli.py").is_ok());
    assert!(validate_script_path("../outside.py").is_err());
    assert!(validate_script_path("C:\\temp\\evil.py").is_err());
}
```

- [ ] **Step 2: Cargo testで失敗を確認する**

Run: `cd gui-tauri; cargo test --manifest-path src-tauri/Cargo.toml`  
Expected: FAIL because `validate_script_path` does not exist

- [ ] **Step 3: run_scriptのパス制限を実装する**

`script` は正規化後に `repo_root` 配下であり、`workflow/cli.py`、`src/cli.py`、`runner/*.py` の許可対象に一致する場合だけ実行する。絶対パス、`..`、シンボリックリンクによるルート外参照を拒否する。コマンド表示では認証・DB一時設定パスを `<temporary-config>` に置換する。

- [ ] **Step 4: 実行環境診断を実装する**

`diagnose_runtime` は Python の起動可否、バージョン、`workflow/cli.py`、`src/cli.py`、`runner/runner.py` の存在を確認し、秘密情報を含まない構造体を返す。GUI 起動時の失敗はアプリ全体を停止せず、「Pythonを確認」「詳細」の行動を表示する。

- [ ] **Step 5: Rust・JS回帰テストを通す**

Run: `cd gui-tauri; cargo test --manifest-path src-tauri/Cargo.toml`  
Expected: PASS

Run: `cd gui-tauri; cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings`  
Expected: PASS

Run: `cd gui-tauri; npm test -- --run`  
Expected: PASS

- [ ] **Step 6: コミットする**

```powershell
git add gui-tauri/src-tauri/src/lib.rs gui-tauri/src/main.js gui-tauri/src/index.html
git commit -m "fix: Tauriの実行スクリプト制限と環境診断を追加"
```

### Task 8: ローカル検証、ドキュメント、配布確認

**Files:**
- Create: `scripts/verify-local.ps1`
- Modify: `README.md`
- Modify: `gui-tauri/README.md`
- Test: repository-wide

**Interfaces:**
- Produces: `powershell -ExecutionPolicy Bypass -File scripts/verify-local.ps1`
- Consumes: pytest、ruff、npm、cargo

- [ ] **Step 1: 一括検証スクリプトを実装する**

`$ErrorActionPreference = "Stop"` を設定し、次を順番に実行する。

```powershell
python -m pytest tests workflow/tests runner/tests -q
ruff check .
Push-Location gui-tauri
try {
    npm test -- --run
    npm run lint
    cargo test --manifest-path src-tauri/Cargo.toml
    cargo clippy --manifest-path src-tauri/Cargo.toml --all-targets -- -D warnings
} finally {
    Pop-Location
}
```

各コマンドの終了コードが非0なら即時終了し、最後に成功した検証項目一覧を表示する。

- [ ] **Step 2: ドキュメントを新ワークフローへ更新する**

README に「プロジェクトを作る→OpenAPIを確認→試験を確認→実行→結果」の操作を記載する。`gui-tauri/README.md` に Python 診断、開発実行、ビルド、同梱リソース、ローカル一括検証を記載する。GitHub Actions を利用手順として要求しない。

- [ ] **Step 3: 全ローカル検証を実行する**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify-local.ps1`  
Expected: all Python tests, ruff, Vitest, ESLint, Cargo tests and Clippy pass

- [ ] **Step 4: 配布ビルドを作成する**

Run: `cd gui-tauri; npm run tauri build`  
Expected: `gui-tauri/src-tauri/target/release/gui-tauri.exe` and installer bundles are created

- [ ] **Step 5: 配布物のスモークテストを行う**

ビルドした exe を起動し、診断画面が Python と同梱 `workflow/` を検出すること、サンプル OpenAPI を開けること、ドライランを開始・キャンセルできることを確認する。結果を `docs/report.md` のフェーズ 1 受入記録へ追記する。

- [ ] **Step 6: コミットする**

```powershell
git add scripts/verify-local.ps1 README.md gui-tauri/README.md docs/report.md
git commit -m "docs: 統合ワークフローのローカル検証と利用手順を追加"
```

## Final Verification

- [ ] `git status --short` に意図しない変更がないことを確認する。
- [ ] `docs/test_cases.json` など既存の未追跡生成物をコミットしない。
- [ ] `powershell -ExecutionPolicy Bypass -File scripts/verify-local.ps1` を再実行する。
- [ ] Tauri 配布ビルドを作成し、exe のスモークテストを行う。
- [ ] `git log --oneline` で各タスクが独立コミットになっていることを確認する。
