//! openapi-test-gen/runner のTauriシェル。
//!
//! 既存のPythonエンジン（src/・runner/）とgui/validators.pyの検証ロジックはそのまま使い、
//! ここではプロセス起動・ストリーミング出力・ネイティブファイルダイアログ・設定永続化
//! といった「OSとの橋渡し」だけを担当する（PySide6版gui/app.pyの役割と同じ）。

use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::process::Command as StdCommand;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};

/// src/・runner/・gui/tauri_bridge.py等が置かれているルート。
///
/// 配布用ビルド（tauri build）では、tauri.conf.jsonのbundle.resourcesで
/// 同梱したPythonソース一式がresource_dir()配下に展開されるので、そちらを優先する。
/// resource_dir()が取得できない、またはrunner/が存在しない（＝tauri dev実行時。
/// dev buildではresourcesが展開されない）場合は、コンパイル時のCARGO_MANIFEST_DIRから
/// リポジトリ直下（src-tauri/の2階層上）を逆算する開発時フォールバックを使う。
fn repo_root(app: &AppHandle) -> PathBuf {
    if let Ok(resource_dir) = app.path().resource_dir() {
        if resource_dir.join("runner").is_dir() {
            return resource_dir;
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("gui-tauri")
        .parent()
        .expect("api-tester")
        .to_path_buf()
}

fn bundled_python_executable(root: &Path) -> Option<PathBuf> {
    let executable = root.join("runtime").join("python").join("python.exe");
    executable.is_file().then_some(executable)
}

fn python_executable(root: &Path) -> PathBuf {
    bundled_python_executable(root).unwrap_or_else(|| PathBuf::from("python"))
}

fn validate_script_path(root: &Path, script: &str) -> Result<PathBuf, String> {
    // GUIから起動する用途を、既存CLIと統一ワークフローに限定する。絶対パス、親階層、
    // シンボリックリンクによるルート外参照を受け入れると、IPCを経由して任意のPythonを
    // 起動できてしまうため、文字列の許可リストとcanonicalizeの両方で検証する。
    let normalized = script.replace('\\', "/");
    let allowed = normalized == "workflow/cli.py"
        || normalized == "src/cli.py"
        || (normalized.starts_with("runner/")
            && normalized.ends_with(".py")
            && !normalized["runner/".len()..].contains('/'));
    if !allowed {
        return Err("このスクリプトは実行できません".to_string());
    }

    let root = root
        .canonicalize()
        .map_err(|_| "アプリケーションの実行フォルダを確認できません".to_string())?;
    let candidate = root.join(normalized);
    let resolved = candidate
        .canonicalize()
        .map_err(|_| "実行に必要なスクリプトが見つかりません".to_string())?;
    if !resolved.starts_with(&root) {
        return Err("このスクリプトは実行できません".to_string());
    }
    Ok(resolved)
}

fn display_command(python: &Path, script_path: &Path, args: &[String]) -> String {
    let secret_path_flags = ["--config", "--auth-config", "--runtime-config"];
    let mut redact_next = false;
    let rendered_args = args
        .iter()
        .map(|arg| {
            if redact_next {
                redact_next = false;
                return "<temporary-config>".to_string();
            }
            if secret_path_flags.contains(&arg.as_str()) {
                redact_next = true;
            }
            arg.clone()
        })
        .collect::<Vec<_>>();
    format!("$ {} -u {} {}", python.display(), script_path.display(), rendered_args.join(" "))
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct RuntimeDiagnosis {
    python_available: bool,
    python_version: Option<String>,
    python_bundled: bool,
    workflow_available: bool,
    generator_available: bool,
    runner_available: bool,
}

#[tauri::command]
fn app_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[tauri::command]
fn diagnose_runtime(app: AppHandle) -> RuntimeDiagnosis {
    let root = repo_root(&app);
    let python_path = python_executable(&root);
    let python_bundled = bundled_python_executable(&root).is_some();
    let python = StdCommand::new(&python_path).arg("--version").output();
    let (python_available, python_version) = match python {
        Ok(output) if output.status.success() => {
            let text = String::from_utf8_lossy(&output.stdout).trim().to_string();
            let text = if text.is_empty() {
                String::from_utf8_lossy(&output.stderr).trim().to_string()
            } else {
                text
            };
            (true, Some(text))
        }
        _ => (false, None),
    };
    RuntimeDiagnosis {
        python_available,
        python_version,
        python_bundled,
        workflow_available: root.join("workflow").join("cli.py").is_file(),
        generator_available: root.join("src").join("cli.py").is_file(),
        runner_available: root.join("runner").join("runner.py").is_file(),
    }
}

/// PySide6版と同じ場所・同じ形式の設定ファイルを共有する（移行期間中はどちらのGUIでも
/// 同じ設定を引き継げるようにするため）。
fn settings_path() -> PathBuf {
    let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".to_string());
    PathBuf::from(home).join(".openapi_test_gui_settings.json")
}

#[derive(Default)]
struct RunningProcesses(Mutex<HashMap<String, Child>>);

#[derive(Clone, Serialize)]
struct ProcLine {
    #[serde(rename = "runId")]
    run_id: String,
    line: String,
}

#[derive(Clone, Serialize)]
struct ProcDone {
    #[serde(rename = "runId")]
    run_id: String,
    code: i32,
}

/// runner/・src/配下のCLIスクリプトを `python -u <script> <args...>` として起動し、
/// 標準出力・標準エラーを1行ずつ "proc-line" イベントでフロントエンドへ流す。
/// 完了時に "proc-done" イベントで終了コードを通知する。
#[tauri::command]
async fn run_script(
    app: AppHandle,
    state: State<'_, RunningProcesses>,
    run_id: String,
    script: String,
    args: Vec<String>,
) -> Result<(), String> {
    let root = repo_root(&app);
    let script_path = validate_script_path(&root, &script)?;

    let python_path = python_executable(&root);
    let cmd_line = display_command(&python_path, &script_path, &args);
    let _ = app.emit(
        "proc-line",
        ProcLine { run_id: run_id.clone(), line: cmd_line },
    );

    let mut child = Command::new(&python_path)
        .arg("-u")
        .arg(&script_path)
        .args(&args)
        .current_dir(&root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("プロセスの起動に失敗しました: {e}"))?;

    let stdout = child.stdout.take().expect("stdout piped");
    let stderr = child.stderr.take().expect("stderr piped");

    let app_out = app.clone();
    let run_id_out = run_id.clone();
    let out_task = tokio::spawn(async move {
        let mut lines = BufReader::new(stdout).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let _ = app_out.emit(
                "proc-line",
                ProcLine { run_id: run_id_out.clone(), line },
            );
        }
    });

    let app_err = app.clone();
    let run_id_err = run_id.clone();
    let err_task = tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let _ = app_err.emit(
                "proc-line",
                ProcLine { run_id: run_id_err.clone(), line },
            );
        }
    });

    state.0.lock().unwrap().insert(run_id.clone(), child);

    let _ = out_task.await;
    let _ = err_task.await;

    let code = {
        let mut map = state.0.lock().unwrap();
        map.remove(&run_id)
    };
    let code = match code {
        Some(mut child) => match child.wait().await {
            Ok(status) => status.code().unwrap_or(-1),
            Err(_) => -1,
        },
        None => -1,
    };

    let _ = app.emit("proc-done", ProcDone { run_id, code });
    Ok(())
}

/// 実行中のプロセスをキャンセルする（GUI終了時・キャンセルボタン用）。
#[tauri::command]
fn cancel_script(state: State<'_, RunningProcesses>, run_id: String) -> Result<(), String> {
    let mut map = state.0.lock().unwrap();
    if let Some(child) = map.get_mut(&run_id) {
        terminate_child_tree(child);
    }
    Ok(())
}

fn taskkill_args(pid: u32) -> [String; 4] {
    ["/PID".into(), pid.to_string(), "/T".into(), "/F".into()]
}

fn terminate_child_tree(child: &mut Child) {
    #[cfg(windows)]
    if let Some(pid) = child.id() {
        let terminated = std::process::Command::new("taskkill")
            .args(taskkill_args(pid))
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_ok_and(|status| status.success());
        if terminated {
            return;
        }
    }

    let _ = child.start_kill();
}

/// gui/validators.pyの検証ロジック（openapi.jsonのoperation一覧化・各種ファイル検証）を
/// そのまま呼び出す薄いブリッジ。Rust側でOpenAPIパーサ等を再実装しない。
#[tauri::command]
async fn bridge_call(
    app: AppHandle,
    command: String,
    args: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let root = repo_root(&app);
    let bridge_path = root.join("gui").join("tauri_bridge.py");
    let request = serde_json::json!({ "command": command, "args": args });

    let python_path = python_executable(&root);
    let mut child = Command::new(&python_path)
        .arg("-u")
        .arg(&bridge_path)
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("ブリッジの起動に失敗しました: {e}"))?;

    {
        let mut stdin = child.stdin.take().expect("stdin piped");
        let payload = serde_json::to_vec(&request).map_err(|e| e.to_string())?;
        stdin.write_all(&payload).await.map_err(|e| e.to_string())?;
        stdin.shutdown().await.map_err(|e| e.to_string())?;
    }

    let output = child.wait_with_output().await.map_err(|e| e.to_string())?;
    let stdout_str = String::from_utf8_lossy(&output.stdout);
    let response: serde_json::Value = serde_json::from_str(stdout_str.trim()).map_err(|e| {
        let stderr_str = String::from_utf8_lossy(&output.stderr);
        format!("ブリッジの応答を解析できませんでした: {e}\nstdout={stdout_str}\nstderr={stderr_str}")
    })?;

    if response.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        Ok(response.get("result").cloned().unwrap_or(serde_json::Value::Null))
    } else {
        Err(response
            .get("error")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown error")
            .to_string())
    }
}

/// DB接続設定（postgres/influxdb）をJSONファイルとして書き出す。
/// pathを指定すればそこへ（GUIの「ファイルに保存」用）、
/// 指定しなければOS一時フォルダへ書き出し、実際に書いたパスを返す
/// （runner側が今もファイルパスでしかconfigを受け取れないため、実行時の橋渡し用）。
#[tauri::command]
fn write_config_file(path: Option<String>, data: serde_json::Value) -> Result<String, String> {
    let text = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    let target = match path {
        Some(p) => PathBuf::from(p),
        None => {
            let nanos = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0);
            std::env::temp_dir().join(format!("openapi-test-gui-config-{nanos}.json"))
        }
    };
    std::fs::write(&target, text).map_err(|e| e.to_string())?;
    Ok(target.to_string_lossy().to_string())
}

/// write_config_file(path: None, ...)で作った一時ファイルを実行後に片付ける
/// （パスワードを含むため、使い終わったら残さない）。失敗してもフロント側は無視してよい。
#[tauri::command]
fn delete_file(path: String) -> Result<(), String> {
    std::fs::remove_file(&path).map_err(|e| e.to_string())
}

/// 出力先フォルダが無ければ作成する（実行直前に呼ぶ）。
/// 既存のファイル（フォルダではない）が同じパスにある場合はエラーにして
/// 実行前にはっきり伝える（openapi.jsonのパスをそのまま出力先フォルダ欄に
/// 入れてしまった、等の入力ミスをrunner起動前に検知するため）。
#[tauri::command]
fn ensure_output_dir(path: String) -> Result<(), String> {
    let target = PathBuf::from(&path);
    if target.is_file() {
        return Err(format!("出力先フォルダに指定されたパスは既にファイルとして存在します（フォルダではありません）: {path}"));
    }
    std::fs::create_dir_all(&target).map_err(|e| format!("出力先フォルダを作成できませんでした: {e}"))
}

#[tauri::command]
fn load_settings() -> serde_json::Value {
    let path = settings_path();
    std::fs::read_to_string(&path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| serde_json::json!({}))
}

#[tauri::command]
fn save_settings(data: serde_json::Value) -> Result<(), String> {
    let path = settings_path();
    let text = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    std::fs::write(&path, text).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(RunningProcesses::default())
        .invoke_handler(tauri::generate_handler![
            run_script,
            cancel_script,
            bridge_call,
            write_config_file,
            delete_file,
            ensure_output_dir,
            app_version,
            diagnose_runtime,
            load_settings,
            save_settings,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 各テスト専用の一時フォルダを用意する（並列実行しても他テストと衝突しないよう、
    /// ナノ秒タイムスタンプ + プロセスID相当のランダム性を使う）。
    fn unique_temp_dir(label: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("openapi-test-gui-test-{label}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn process_tree_kill_uses_only_the_tracked_pid() {
        assert_eq!(taskkill_args(1234), ["/PID", "1234", "/T", "/F"]);
    }

    #[test]
    fn bundled_python_is_selected_when_it_exists_beside_resources() {
        let root = unique_temp_dir("bundled-python");
        let executable = root.join("runtime").join("python").join("python.exe");
        std::fs::create_dir_all(executable.parent().unwrap()).unwrap();
        std::fs::write(&executable, "test executable").unwrap();

        assert_eq!(python_executable(&root), executable);

        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn system_python_is_selected_when_no_bundled_runtime_exists() {
        let root = unique_temp_dir("system-python-fallback");

        assert_eq!(python_executable(&root), PathBuf::from("python"));

        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn app_version_matches_the_cargo_package_version() {
        assert_eq!(app_version(), env!("CARGO_PKG_VERSION"));
    }

    #[test]
    fn workflow_script_is_allowed_but_external_paths_are_rejected() {
        let root = unique_temp_dir("script-path");
        for relative in ["workflow/cli.py", "src/cli.py", "runner/runner.py"] {
            let path = root.join(relative);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, "# test").unwrap();
            assert!(validate_script_path(&root, relative).is_ok());
        }

        assert!(validate_script_path(&root, "../outside.py").is_err());
        assert!(validate_script_path(&root, "C:\\temp\\evil.py").is_err());
        assert!(validate_script_path(&root, "gui/tauri_bridge.py").is_err());

        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn display_command_redacts_temporary_runtime_config_paths() {
        let line = display_command(
            PathBuf::from("C:/app/runtime/python/python.exe").as_path(),
            PathBuf::from("C:/app/workflow/cli.py").as_path(),
            &["--config".into(), "C:/temp/db.json".into(), "--auth-config".into(), "C:/temp/auth.json".into()],
        );

        assert!(line.contains("<temporary-config>"));
        assert!(line.contains("C:/app/runtime/python/python.exe"));
        assert!(!line.contains("C:/temp/db.json"));
        assert!(!line.contains("C:/temp/auth.json"));
    }

    // ---------- write_config_file / delete_file ----------

    #[test]
    fn write_config_file_with_explicit_path_writes_pretty_json() {
        let dir = unique_temp_dir("write-explicit");
        let target = dir.join("config.json");
        let data = serde_json::json!({"postgres": {"host": "127.0.0.1", "port": 5432}});

        let written_path = write_config_file(Some(target.to_string_lossy().to_string()), data.clone()).unwrap();

        assert_eq!(written_path, target.to_string_lossy());
        let content = std::fs::read_to_string(&target).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
        assert_eq!(parsed, data);

        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn write_config_file_without_path_uses_os_temp_dir_and_is_deletable() {
        let data = serde_json::json!({"influxdb": {"host": "h", "port": 8086}});

        let written_path = write_config_file(None, data.clone()).unwrap();
        let path_buf = PathBuf::from(&written_path);

        assert!(path_buf.starts_with(std::env::temp_dir()));
        let content = std::fs::read_to_string(&path_buf).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&content).unwrap();
        assert_eq!(parsed, data);

        // delete_file（実行後の後片付けに使われる関数）で実際に消せること
        delete_file(written_path.clone()).unwrap();
        assert!(!path_buf.exists());
    }

    #[test]
    fn delete_file_on_nonexistent_path_returns_err() {
        let dir = unique_temp_dir("delete-missing");
        let missing = dir.join("does-not-exist.json");

        let result = delete_file(missing.to_string_lossy().to_string());

        assert!(result.is_err());
        std::fs::remove_dir_all(&dir).ok();
    }

    // ---------- ensure_output_dir ----------

    #[test]
    fn ensure_output_dir_creates_nested_directories() {
        let dir = unique_temp_dir("ensure-nested");
        let nested = dir.join("a").join("b").join("c");

        ensure_output_dir(nested.to_string_lossy().to_string()).unwrap();

        assert!(nested.is_dir());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn ensure_output_dir_is_idempotent_when_already_exists() {
        let dir = unique_temp_dir("ensure-idempotent");

        // 既に存在するフォルダに対して呼んでもエラーにならない
        let result = ensure_output_dir(dir.to_string_lossy().to_string());

        assert!(result.is_ok());
        std::fs::remove_dir_all(&dir).ok();
    }

    #[test]
    fn ensure_output_dir_errors_when_path_is_an_existing_file() {
        let dir = unique_temp_dir("ensure-file-conflict");
        let file_path = dir.join("not-a-directory.txt");
        std::fs::write(&file_path, "content").unwrap();

        let result = ensure_output_dir(file_path.to_string_lossy().to_string());

        assert!(result.is_err());
        assert!(result.unwrap_err().contains("既にファイルとして存在します"));
        std::fs::remove_dir_all(&dir).ok();
    }

    // ---------- IPCイベントペイロードのシリアライズ形式 ----------
    // main.js 側は "runId"（キャメルケース）を読む前提のため、#[serde(rename = "runId")]
    // が外れる/typoする退行を検知する回帰テスト。

    #[test]
    fn proc_line_serializes_with_camel_case_run_id() {
        let payload = ProcLine { run_id: "abc123".to_string(), line: "hello".to_string() };
        let json = serde_json::to_value(&payload).unwrap();
        assert_eq!(json["runId"], "abc123");
        assert_eq!(json["line"], "hello");
        assert!(json.get("run_id").is_none());
    }

    #[test]
    fn proc_done_serializes_with_camel_case_run_id() {
        let payload = ProcDone { run_id: "abc123".to_string(), code: 0 };
        let json = serde_json::to_value(&payload).unwrap();
        assert_eq!(json["runId"], "abc123");
        assert_eq!(json["code"], 0);
        assert!(json.get("run_id").is_none());
    }
}
