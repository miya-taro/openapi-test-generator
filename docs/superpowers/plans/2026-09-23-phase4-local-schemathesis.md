# Phase 4A: Local Schemathesis Exploration Implementation Plan

> **For agentic workers:** Execute this approved phase slice inline, task by task, using TDD and the existing workflow contracts.

**Goal:** Run local Schemathesis exploration from the Tauri GUI, defaulting to GET-only, while keeping reports, authentication material, cancellation, and evidence local and reviewable.

**Architecture:** `workflow/cli.py` will delegate Schemathesis command construction and evidence rendering to small workflow modules. It will invoke the installed local Schemathesis CLI, emit the standard workflow events, and pass login credentials only through a temporary environment variable referenced by a temporary TOML file. Tauri will expose a compact exploratory-test panel, require explicit confirmation before including mutating methods, and display local report artifacts.

**Tech Stack:** Python 3.12, Schemathesis CLI 4.x, pytest, Tauri 2 / Rust, Vitest / jsdom.

**Spec:** `docs/superpowers/specs/2026-09-22-local-api-test-automation-design.md` sections 2, 6.4, 6.7, 6.8, and 6.9; `docs/superpowers/plans/2026-09-22-api-test-automation-roadmap.md` Phase 4.

## Global Constraints

- Keep all project/API/test data local; never enable a cloud report or upload path.
- Include only `GET` operations by default; mutating methods require an explicit GUI confirmation and command option.
- Use one worker, a bounded number of examples, and a fixed seed by default.
- Never place auth tokens or passwords in process arguments, manifests, logs, or checked-in files.
- Keep VCR capture optional because responses can contain sensitive data; show that warning in the GUI.
- Every new operation must be available from the official Tauri GUI.
- Preserve the existing Phase 3 approved-case workflow and the user's untracked `docs/test_cases.json`.

---

### Task 1: Schemathesis command and local evidence writer

**Files:**
- Create: `workflow/schemathesis_runner.py`
- Create: `workflow/schemathesis_report.py`
- Create: `workflow/tests/test_schemathesis_runner.py`
- Create: `workflow/tests/test_schemathesis_report.py`

**Interfaces:**
- `build_schemathesis_command(executable: str, schema_path: Path, base_url: str, junit_path: Path, cassette_path: Path | None, *, include_mutating: bool, max_examples: int, config_path: Path | None = None) -> list[str]`
- `write_exploratory_html(junit_path: Path, output_path: Path, *, title: str) -> None`

- [x] **Step 1: Write tests proving the safety and output contract** — assert the literal CLI arguments contain `--include-method GET` by default, omit that filter only with `include_mutating=True`, keep all outputs under the supplied run directory, and never put an auth value into arguments. Assert the HTML report escapes JUnit-provided text.
- [x] **Step 2: Run the focused tests and confirm they fail** — `python -m pytest workflow/tests/test_schemathesis_runner.py workflow/tests/test_schemathesis_report.py -q` must fail because the modules do not exist.
- [x] **Step 3: Implement the smallest command builder and HTML writer** — use `--workers 1`, `--max-examples`, `--seed 1`, `--request-timeout 10`, `--generation-database none`, JUnit output, optional VCR output, and the `examples,coverage,fuzzing` phases; render summaries via `xml.etree.ElementTree` and `html.escape`.
- [x] **Step 4: Re-run the focused tests** — the same command must pass.

**Additional regression found before feature work:** Tauri invokes `workflow/cli.py` directly by path, which previously failed to import the `workflow` package. This is fixed in the current worktree with a subprocess regression test. Keep this fix in the same verified commit.

### Task 2: Local workflow CLI and transient token handling

**Files:**
- Modify: `workflow/cli.py`
- Modify: `workflow/commands.py` only if artifact path allocation requires a shared field
- Modify: `workflow/tests/test_cli.py`
- Create or update: `docs/requirements-schemathesis.txt`, `README.md`

**Interfaces:**
- CLI command: `run-schemathesis --project PATH [--include-mutating] [--max-examples N] [--auth-config PATH] [--save-cassette]`
- The command emits `artifact` events for the run manifest, JUnit XML, HTML summary, and optional VCR cassette, then a standard `workflow_finished` event.

- [x] **Step 1: Add CLI tests first** — fake `shutil.which`, `perform_login`, and `run_command`; assert absent Schemathesis produces a clear installation error without creating an API request, the default command contains only GET, and a token appears only in the child environment/config substitution (never in args or manifest).
- [x] **Step 2: Run the new CLI tests and confirm expected failures** — `python -m pytest workflow/tests/test_cli.py -k schemathesis -q` must fail before implementation.
- [x] **Step 3: Implement the workflow** — create a unique run directory, validate max_examples in 1..100, locate the installed schemathesis executable, perform existing token login when configured, write a run-local TOML config containing only the API_TESTER_SCHEMATHESIS_HEADER placeholder, copy the auth header only into the child process environment, and never mutate the parent environment. Keep the credential-free config as local run evidence; the GUI removes temporary project/auth files in finally.
- [x] **Step 5: Verify focused workflow tests** — `python -m pytest workflow/tests/test_cli.py -k schemathesis -q` must pass.

`run_command` currently treats exit code 2 as a warning for the legacy runner. Schemathesis uses different exit-code meanings, so add an optional warning-code set to `run_command`; call it with an empty set for Schemathesis and normalize its non-test/configuration errors to the workflow's generic error code so the GUI does not mislabel them as warnings.

### Task 3: Tauri GUI entry and mutation guard

**Files:**
- Modify: `gui-tauri/src/workflow-client.js`
- Modify: `gui-tauri/src/index.html`
- Modify: `gui-tauri/src/main.js`
- Modify: `gui-tauri/src/styles.css`
- Modify: `gui-tauri/tests/workflow-client.test.js`
- Modify: `gui-tauri/tests/main.test.js`

**Interfaces:**
- `createWorkflowClient().runSchemathesis({ projectPath, authConfigPath, includeMutating, maxExamples, saveCassette }, { onEvent })`
- The GUI uses existing project and auth settings; token inputs remain transient and are never persisted.

- [x] **Step 1: Add Vitest cases first** — verify the workflow client builds the expected local-only CLI args, and the GUI refuses to launch mutating exploration unless the user confirms the write-risk dialog.
- [x] **Step 2: Run the targeted Vitest cases and confirm failure** — `npm test -- --run tests/workflow-client.test.js tests/main.test.js` must fail for the missing method and GUI flow.
- [x] **Step 3: Add one compact optional panel** — default checkbox off for mutating methods, example count default 10 with a 1..100 bound, optional cassette checkbox off, clear local-response-data warning, run/cancel state, and the existing artifact links/log display.
- [x] **Step 4: Re-run Vitest and lint** — `npm test -- --run tests/workflow-client.test.js tests/main.test.js` and `npm run lint` must pass.

### Task 4: Cancel nested test processes safely

**Files:**
- Modify: `gui-tauri/src-tauri/src/lib.rs`

**Interfaces:**
- `cancel_script` terminates the complete process tree rooted at the tracked Python child on Windows, falling back to the direct child kill if `taskkill` fails.

- [x] **Step 1: Add a unit test for the exact PID-scoped tree-kill arguments** — the expected argument vector is `[/PID, <pid>, /T, /F]`; no process-wide name matching is allowed.
- [x] **Step 2: Run `cargo test` and confirm the test fails before implementation.**
- [x] **Step 3: Implement PID-scoped `taskkill /T /F` with a direct-child fallback** — suppress helper output and retain existing run-map lifecycle.
- [x] **Step 4: Run `cargo test` and `cargo clippy --all-targets -- -D warnings`.**

### Task 5: Real local-server acceptance and documentation

**Files:**
- Modify: `README.md`
- Modify: `gui-tauri/README.md`
- Add tests only where a concrete workflow edge is not already covered.

- [x] **Step 1: Run Schemathesis 4.x against a temporary local HTTP server and tiny OpenAPI file** — verify GET filtering, successful JUnit output, optional VCR output, and no network dependency beyond loopback.
- [x] **Step 2: Run the complete Python suite, Tauri Vitest, ESLint, Rust tests, Clippy, and production frontend build.**
- [x] **Step 3: Run `git diff --check`, inspect the final diff, and commit the verified local changes.**

---
