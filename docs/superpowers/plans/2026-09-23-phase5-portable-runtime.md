# Phase 5 Portable Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows Tauri distribution that carries a minimal CPython runtime and the API tester's runtime dependencies, so the app can run without Python being installed separately.

**Architecture:** A local packaging script copies the Python interpreter and standard library from the build machine, then copies only the dependency closure declared by `requirements-runtime.txt` into the bundled runtime. Tauri resolves that runtime beside its packaged Python resources and falls back to `python` from PATH for development. The same resource layout is copied beside a portable executable, while the existing MSI and NSIS bundles include the runtime through Tauri's resource map.

**Tech Stack:** CPython on Windows, Python `importlib.metadata` and `packaging`, PowerShell, Tauri 2, Rust, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-local-api-test-automation-design.md` (Phase 5)

## Global Constraints

- The maintained desktop application is the Tauri GUI.
- Existing Python CLI entry points remain the execution interface.
- The packaged runtime is built offline from an installed Python environment; the app does not download packages at startup.
- Runtime dependencies are separated from test and development dependencies.
- Development continues to use a PATH-installed Python when no bundled runtime exists.
- Python source, database credentials, and test artifacts are not uploaded to GitHub.
- The distributable must retain the existing local-only API and database execution behavior.

---

### Task 1: Define and assemble the minimal runtime

**Files:**
- Create: `requirements-runtime.txt`
- Modify: `requirements-dev.txt`
- Modify: `requirements.txt`
- Create: `scripts/package_runtime.py`
- Create: `tests/test_package_runtime.py`
- Modify: `.gitignore`

**Interfaces:**
- `load_runtime_requirements(path: Path) -> list[Requirement]` reads only runtime package requirements.
- `resolve_distribution_closure(requirements, distributions) -> list[Distribution]` validates installed versions and returns direct plus active transitive dependencies once each.
- `build_runtime(source_python: Path, output: Path, requirements_file: Path | Iterable[Path]) -> dict` writes the interpreter, standard library, selected package files, and a JSON package manifest.

- [x] **Step 1: Write dependency-resolution tests** for transitive requirements, duplicate dependencies, false environment markers, missing distributions, and an installed version that fails its specifier.
- [x] **Step 2: Run `python -m pytest tests/test_package_runtime.py -q`** and confirm the new tests fail because the packaging module does not exist.
- [x] **Step 3: Split production dependencies** into `requirements-runtime.txt`, add `packaging` to `requirements-dev.txt`, and make `requirements.txt` include the runtime file plus only test dependencies.
- [x] **Step 4: Implement the packager** so it copies `python.exe`, matching Python DLLs, `DLLs/`, `Lib/` without its existing `site-packages`, Tcl support files when present, CPython's license, and only the installed files listed by the resolved runtime distributions. Write `pythonXY._pth` with `.`, `DLLs`, `Lib`, and `Lib/site-packages` entries, without enabling user-site customization. Emit `runtime-manifest.json` containing the Python version and exact copied package versions.
- [x] **Step 5: Build an isolated runtime staging directory** with both `requirements-runtime.txt` and `docs/requirements-schemathesis.txt`, then run its `python.exe --version` plus imports for `requests`, `openpyxl`, `jsonschema`, `yaml`, `psycopg2`, `influxdb`, `exrex`, and `schemathesis`.
- [x] **Step 6: Run the package-runtime tests and `ruff check scripts tests`**.

### Task 2: Make Tauri use the bundled interpreter

**Files:**
- Modify: `gui-tauri/src-tauri/src/lib.rs`
- Modify: `gui-tauri/src-tauri/tauri.conf.json`
- Modify: `gui-tauri/src/index.html`
- Modify: `gui-tauri/src/main.js`
- Modify: `gui-tauri/src/styles.css`
- Modify: `gui-tauri/tests/main.test.js`
- Create: `.build/python-runtime/.gitkeep`

**Interfaces:**
- `python_executable(root: &Path) -> PathBuf` returns `root/runtime/python/python.exe` when present, otherwise `PathBuf::from("python")`.
- `diagnose_runtime` and every Python subprocess command use the same resolved executable.
- `RuntimeDiagnosis.python_bundled: bool` reports whether the bundled interpreter was selected.
- An `app_version` command exposes Cargo's package version in the GUI footer.

- [x] **Step 1: Add Rust tests** proving the bundled path wins when present and PATH fallback is selected when absent.
- [x] **Step 2: Run `cargo test --manifest-path gui-tauri/src-tauri/Cargo.toml`** and confirm the bundled-runtime test fails before implementation.
- [x] **Step 3: Add the shared interpreter resolver** and use it in runtime diagnosis, normal script execution, and one-shot script execution.
- [x] **Step 4: Map `../../.build/python-runtime` to `runtime/python`** in Tauri resources so MSI and NSIS bundles carry the generated interpreter directory.
- [x] **Step 5: Run the Rust tests and `cargo clippy --manifest-path gui-tauri/src-tauri/Cargo.toml -- -D warnings`**.

### Task 3: Produce and document the portable distribution

**Files:**
- Create: `scripts/package-portable.ps1`
- Modify: `gui-tauri/README.md`
- Modify: `README.md`
- Test: `scripts/verify-local.ps1`

**Interfaces:**
- `powershell -ExecutionPolicy Bypass -File scripts/package-portable.ps1` builds the isolated runtime, Tauri executable, MSI/NSIS installers, and `dist/openapi-test-tool-portable/` without network access.
- The portable folder contains `openapi-test-tool.exe`, `runtime/python/`, and the Python source resources expected by `repo_root()`.
- The build machine has CPython satisfying `requirements-runtime.txt`, `node_modules`, and the Cargo cache; package creation downloads no dependencies.

- [x] **Step 1: Write and execute the package script** to stop on failed native commands, build the Python runtime, invoke `npm run tauri build`, and copy the app executable plus the exact resource layout into the portable output directory.
- [x] **Step 2: Document prerequisites and outputs**, including WebView2 behavior and Schemathesis dependencies in the portable runtime.
- [x] **Step 3: Run `powershell -ExecutionPolicy Bypass -File scripts/verify-local.ps1`**.
- [x] **Step 4: Run the packaging command with network access disabled**, launch the bundled Python import smoke test, and launch the portable Tauri app to confirm its process and main window handle.
- [x] **Step 5: Confirm the MSI/NSIS artifacts exist, the portable executable's resource hashes match the source, and the app falls back to PATH Python when the bundled runtime is absent.**

The desktop smoke check verifies that the portable executable remains running and creates a Windows window handle. Interactive visual acceptance and installation on a clean target VM remain separate checks.

## Acceptance Limits

- A portable build and installer can be produced on the current Windows build machine without network access.
- The bundled interpreter launches and imports every required runtime dependency without a system Python installation.
- The Tauri application starts from the portable output and resolves its bundled source resources.
- Installation and first-run acceptance on a clean target VM remains a separate check because its Windows version, install policy, and WebView2 state are not supplied by the local build machine.
