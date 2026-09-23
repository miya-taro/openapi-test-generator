# Phase 3 Case Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Existing OpenAPI-generated cases and DB scenarios are normalized into one local draft case master that the Tauri GUI exposes with traceable IDs and source references.

**Architecture:** Add a versioned Python case-master adapter in `workflow/` that reads the existing Layer 1 JSON and Layer 2 YAML without changing their execution engines. Both layers use a prepare → review → execute GUI flow. Normal execution requires approval; preliminary runs require a distinct explicit action and are labeled exploratory in the HTML report. The case master, generic specification workbook, runner results, JUnit and HTML report share stable IDs.

**Tech Stack:** Python 3.10+, dataclasses, PyYAML, JSON, pytest, Tauri 2, Vanilla JavaScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-23-phase3-case-master-capability.md`

## Global Constraints

- GitHub、GitHub Actions、外部AI APIを必要とせずローカルで完結する。
- 正式な操作面は `gui-tauri/` とし、新しい成果物をCLIだけに追加しない。
- 既存 `test-cases.json`、Excel、`scenarios.yaml` の形式を壊さない。
- 秘密の実行時DB・認証設定をケースマスターへ取り込まない。
- 自動生成ケースは未承認の `draft` として扱う。
- `docs/test_cases.json` の既存未追跡ファイルは変更・追加しない。

---

## File Structure

- Create `workflow/case_master.py`: versioned master schema, source adapters, stable IDs, validation and JSON writer.
- Modify `workflow/models.py`: add `case_master_json` artifact path.
- Modify `workflow/cli.py`: build the draft master after contract generation or from DB scenarios before a DB-only run; emit its artifact path.
- Modify `gui-tauri/src/main.js`: label the artifact in Japanese; existing artifact UI already renders and opens generated files.
- Create `workflow/tests/test_case_master.py`: valid, incomplete, duplicate-ID, deterministic-ID, and secret-exclusion cases.
- Modify `workflow/tests/test_commands.py` and `workflow/tests/test_cli.py`: artifact path and workflow event regression coverage.
- Modify `gui-tauri/tests/main.test.js`: artifact label coverage if the mapping is exported/testable.
- Modify `docs/superpowers/plans/2026-09-22-api-test-automation-roadmap.md`: record Phase 3 first-slice status and remaining gates.
- Modify `README.md` and `gui-tauri/README.md`: describe the new local case-master artifact and its draft status.

## Interfaces

`build_case_master(project_name: str, contract_output: dict | None, db_scenarios_path: Path | None, openapi_path: Path) -> dict` returns a JSON-serializable object with `format`, `schemaVersion`, `project`, `generatedAt`, and `cases`. Each case has `caseId`, `kind`, `title`, `source`, `definition`, `expected`, and `reviewStatus="draft"`.

Layer 1 IDs are retained. Layer 2 explicit IDs are namespaced as `DB-<id>`; absent IDs are generated as `DB-<12 uppercase hex chars>` from canonical JSON for that scenario. Duplicate final IDs raise `CaseMasterError` with the source item position. Runtime config paths and values are never accepted by this adapter.

### Task 1: Versioned master model and adapters

**Files:** `workflow/case_master.py`, `workflow/tests/test_case_master.py`, `runner/db_scenario.py`

- [x] Write tests for preserving a Layer 1 case ID and mapping the request/expected fields.
- [x] Write tests for converting a DB scenario, generating the same fallback ID after YAML key reordering, honoring an explicit ID, and rejecting duplicate IDs.
- [x] Write tests that runtime config/password/token keys are not represented in the master.
- [x] Implement serializers using only the allowed scenario definition fields (`request`, `given`, `response_check`, `db_check`) and source references; do not serialize DB connection config.
- [x] Run `python -m pytest workflow/tests/test_case_master.py -q` and `ruff check workflow runner/db_scenario.py`.

### Task 2: Workflow artifact generation

**Files:** `workflow/models.py`, `workflow/commands.py`, `workflow/cli.py`, `workflow/tests/test_commands.py`, `workflow/tests/test_cli.py`

- [x] Add `ArtifactPaths.case_master_json` at `<run_dir>/case-master.json`.
- [x] After successful Layer 1 generation, read the generated JSON and merge DB scenarios when the project has a scenario file.
- [x] For a DB-only workflow, create a DB-only draft master from the configured scenario file before execution; leave the original scenario YAML untouched.
- [x] Write UTF-8 JSON and emit `artifact` with `kind="case_master_json"` only after successful validation and save.
- [x] Cover DB-only, mixed input, malformed operation reference, duplicate IDs, deterministic IDs, and secret-config exclusion with workflow tests.
- [x] Run workflow tests as part of the complete Python regression suite and run Ruff on the source directories.

### Task 3: Tauri artifact visibility

**Files:** `gui-tauri/src/main.js`, `gui-tauri/tests/main.test.js`, `gui-tauri/README.md`, `README.md`

- [x] Map `case_master_json` to `試験ケースマスター（下書き）` in the artifact list.
- [x] Verify through the existing artifact button that the JSON path is passed to Tauri's generic local-file opener; opener errors are swallowed and are not inserted into the status text.
- [x] Add Vitest assertions for the Japanese draft label and the existing local-file open action.
- [x] Document the draft status and clarify that Layer 2 result-ID propagation is still future work.
- [x] Run `cd gui-tauri; npm test -- --run; npm run lint`.

### Task 4: Local acceptance and roadmap update

**Files:** roadmap, local report / verification logs

- [x] Run the full Python suite (859 passed), `ruff check src runner workflow gui docs`, Tauri Vitest (50 passed), ESLint, `cargo test` (10 passed), and Clippy with warnings denied.
- [x] Run the workflow against `examples/openapi.json` and `examples/scenarios.yaml`; confirm 105 contract cases + 7 DB scenarios, unique IDs, draft state, and no runtime secret configuration.
- [x] Update the roadmap with this first-slice completion and list remaining Phase 3 work: review UI/state, specification workbook adapter, DB result-ID propagation, HTML report, failed-case rerun, and company template mapping.
- [x] Commit this completed vertical slice as `feat: 試験ケースマスター初版を追加`.

### Task 5: Review-gated execution, reports, and Layer 2 identity

**Files:** `workflow/cli.py`, `workflow/html_report.py`, `workflow/tests/`, `runner/db_scenario_report.py`, `runner/junit_writer.py`, `runner/db_scenario_runner.py`, `gui-tauri/src/`, `gui-tauri/tests/`, user documentation.

- [x] Prepare Layer 1 and Layer 2 cases without HTTP requests or DB connections.
- [x] Show both case sets in Tauri review panels and persist per-case review status against the exact definition fingerprint.
- [x] Require approval for regular execution; allow draft execution only through a separate explicit preview action/flag.
- [x] Rebuild fingerprints from current OpenAPI/YAML/case JSON before execution and reject stale or changed definitions.
- [x] Hash prepared Excel artifacts and reject post-review workbook edits; refresh the review workbook and hash when review status changes.
- [x] Keep case IDs aligned in DB Excel/JUnit and HTML reports; allow failed-case reruns by ID.
- [x] Generate a generic specification Excel and a local HTML result report; escape untrusted content and exclude raw bodies/secrets.
- [x] Fix exploratory-report labeling so unexecuted unapproved cases in another layer do not affect the current run's approval label.
- [x] Run focused tests, complete Python/GUI/Rust verification, local sample acceptance, and Tauri distribution build.
- [ ] Add column/style mapping for the corporate workbook after its template is provided.

## Self-Review

- The plan does not change existing runner input formats; current JSON and YAML remain the execution adapters.
- Contract case IDs are preserved and DB scenario IDs are namespaced, avoiding collisions between layers.
- The source of truth for runtime secrets remains the existing temporary config flow; only test definitions are copied.
- Corporate template columns and evidence retention are explicitly unresolved and are not hard-coded into the internal model.
- The current specification workbook is generic because no corporate template was supplied. It is kept as an adapter boundary; corporate-specific mapping remains dependent on receiving that file.
