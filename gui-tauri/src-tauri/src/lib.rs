//! openapi-test-gen/runner のTauriシェル。
//!
//! 既存のPythonエンジン（src/・runner/）とgui/validators.pyの検証ロジックはそのまま使い、
//! ここではプロセス起動・ストリーミング出力・ネイティブファイルダイアログ・設定永続化
//! といった「OSとの橋渡し」だけを担当する（PySide6版gui/app.pyの役割と同じ）。

use serde::Serialize;
use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, State};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};

/// リポジトリのルート（api-tester/）。src-tauri/の2階層上。
/// 開発ビルド前提（コンパイル時にCARGO_MANIFEST_DIRへ焼き込まれる）。
/// 配布用ビルドでは別途リソース同梱に切り替える必要がある。
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("gui-tauri")
        .parent()
        .expect("api-tester")
        .to_path_buf()
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
    let root = repo_root();
    let script_path = root.join(&script);

    let cmd_line = format!("$ python -u {} {}", script_path.display(), args.join(" "));
    let _ = app.emit(
        "proc-line",
        ProcLine { run_id: run_id.clone(), line: cmd_line },
    );

    let mut child = Command::new("python")
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
        let _ = child.start_kill();
    }
    Ok(())
}

/// gui/validators.pyの検証ロジック（openapi.jsonのoperation一覧化・各種ファイル検証）を
/// そのまま呼び出す薄いブリッジ。Rust側でOpenAPIパーサ等を再実装しない。
#[tauri::command]
async fn bridge_call(
    command: String,
    args: serde_json::Value,
) -> Result<serde_json::Value, String> {
    let root = repo_root();
    let bridge_path = root.join("gui").join("tauri_bridge.py");
    let request = serde_json::json!({ "command": command, "args": args });

    let mut child = Command::new("python")
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
            load_settings,
            save_settings,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
