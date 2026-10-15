"""Loopback browser host for the API test GUI (no Tauri/Rust executable)."""
from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
USER_HOME = Path.home()
DATA = Path(os.environ.get("LOCALAPPDATA", USER_HOME)) / "OpenApiTestTool"
IMPORTS = DATA / "imports"
SAVED = DATA / "saved"
OUTPUT = DATA / "output"
TEMP = DATA / "temp"
SETTINGS = USER_HOME / ".openapi_test_gui_settings.json"
MAX_BODY = 100 * 1024 * 1024
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
SAFE_SCRIPT = re.compile(r"^(workflow/cli\.py|src/cli\.py|runner/[^/]+\.py)$")



_SETTINGS_LOCK = threading.Lock()


def _atomic_write(path: Path, contents: bytes) -> None:
    """Replace only after a complete, flushed write on the same filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_settings(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("設定ファイルはJSONオブジェクトである必要があります")
    data.pop("_settings_warning", None)
    return data


def _load_settings() -> dict:
    backup = SETTINGS.with_name(SETTINGS.name + ".bak")
    try:
        return _read_settings(SETTINGS)
    except FileNotFoundError:
        if not backup.exists():
            return {}
    except (OSError, ValueError):
        pass
    try:
        data = _read_settings(backup)
    except (OSError, ValueError):
        raise ValueError("保存した設定を読み込めず、復旧できるバックアップもありません。元ファイルは保持しています。接続先・API定義を再設定してください。") from None
    data["_settings_warning"] = "設定ファイルを読み込めなかったため、前回保存前のバックアップを表示しています。接続先・API定義を確認してから設定を保存してください。"
    return data


def _save_settings(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("設定はJSONオブジェクトで指定してください")
    data = {key: value for key, value in data.items() if key != "_settings_warning"}
    encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if SETTINGS.exists():
        previous = SETTINGS.read_bytes()
        try:
            _read_settings(SETTINGS)
        except (ValueError, UnicodeError):
            # Preserve a broken original for recovery without replacing a good backup.
            descriptor, name = tempfile.mkstemp(prefix=SETTINGS.name + ".corrupt-", dir=SETTINGS.parent)
            os.close(descriptor)
            _atomic_write(Path(name), previous)
        else:
            _atomic_write(SETTINGS.with_name(SETTINGS.name + ".bak"), previous)
    _atomic_write(SETTINGS, encoded)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


class WebState:
    def __init__(self, static_root: Path):
        self.static_root = static_root.resolve()
        self.token = secrets.token_urlsafe(32)
        self.events: set[queue.Queue] = set()
        self.events_lock = threading.Lock()
        self.processes: dict[str, subprocess.Popen] = {}
        self.processes_lock = threading.Lock()

    def emit(self, name: str, payload: dict) -> None:
        message = (name, json.dumps(payload, ensure_ascii=False))
        with self.events_lock:
            for listener in tuple(self.events):
                try:
                    listener.put_nowait(message)
                except queue.Full:
                    try:
                        listener.get_nowait()
                        listener.put_nowait(message)
                    except queue.Empty:
                        pass

    def require_token(self, value: str | None) -> None:
        if not value or not hmac.compare_digest(value, self.token):
            raise PermissionError("ローカルアプリの認証に失敗しました。画面を再読み込みしてください。")

    def invoke(self, command: str, args: dict):
        if command == "app_version":
            match = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "gui-tauri/src-tauri/Cargo.toml").read_text(encoding="utf-8"), re.M)
            return match.group(1) if match else "不明"
        if command == "diagnose_runtime":
            return {
                "pythonAvailable": True,
                "pythonVersion": sys.version.split()[0],
                "pythonBundled": False,
                "workflowAvailable": (ROOT / "workflow/cli.py").is_file(),
                "generatorAvailable": (ROOT / "src/cli.py").is_file(),
                "runnerAvailable": (ROOT / "runner/pytest_runner.py").is_file(),
            }
        if command == "load_settings":
            with _SETTINGS_LOCK:
                return _load_settings()
        if command == "save_settings":
            with _SETTINGS_LOCK:
                _save_settings(args.get("data", {}))
            return None
        if command == "write_config_file":
            if args.get("path"):
                path = Path(args["path"]).expanduser()
            else:
                descriptor, temp_name = tempfile.mkstemp(prefix="openapi-test-gui-", suffix=".json", dir=TEMP)
                os.close(descriptor)
                path = Path(temp_name)
            if args.get("path") and not _inside(path, DATA):
                raise ValueError("ブラウザー版では設定ファイルをアプリの保存フォルダー内に保存します")
            path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(path, json.dumps(args.get("data"), ensure_ascii=False, indent=2).encode("utf-8"))
            return str(path)
        if command == "delete_file":
            path = Path(args["path"]).expanduser()
            if not _inside(path, DATA):
                raise ValueError("アプリの一時ファイル以外は削除できません")
            path.unlink(missing_ok=True)
            return None
        if command == "ensure_output_dir":
            path = Path(args["path"]).expanduser()
            if path.is_file():
                raise ValueError(f"出力先はファイルではなくフォルダーを指定してください: {path}")
            path.mkdir(parents=True, exist_ok=True)
            return None
        if command == "bridge_call":
            request = json.dumps({"command": args.get("command"), "args": args.get("args", {})}, ensure_ascii=False)
            environment = os.environ.copy()
            environment["PYTHONUTF8"] = "1"
            result = subprocess.run(
                [sys.executable, "-u", str(ROOT / "gui/tauri_bridge.py")],
                input=request,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
                env=environment,
                timeout=120,
                check=False,
            )
            try:
                response = json.loads(result.stdout.strip())
            except json.JSONDecodeError as error:
                raise RuntimeError(f"Pythonブリッジを実行できませんでした: {result.stderr.strip() or error}") from error
            if response.get("ok"):
                return response.get("result")
            raise RuntimeError(response.get("error", "Pythonブリッジに失敗しました"))
        if command == "run_script":
            self.start_script(args)
            return None
        if command == "cancel_script":
            self.cancel_script(args.get("runId") or args.get("run_id", ""))
            return None
        raise ValueError(f"未対応のコマンドです: {command}")

    def start_script(self, args: dict) -> None:
        run_id = str(args.get("runId") or args.get("run_id") or "")
        script = str(args.get("script") or "").replace("\\", "/")
        script_path = (ROOT / script).resolve()
        if not SAFE_RUN_ID.fullmatch(run_id) or not SAFE_SCRIPT.fullmatch(script) or not _inside(script_path, ROOT) or not script_path.is_file():
            raise ValueError("実行する処理を確認できません")
        command_args = args.get("args") or []
        if not isinstance(command_args, list) or not all(isinstance(arg, (str, int, float)) for arg in command_args):
            raise ValueError("コマンド引数の形式が不正です")
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        with self.processes_lock:
            if run_id in self.processes:
                raise ValueError("この処理はすでに実行中です")
            process = subprocess.Popen(
                [sys.executable, "-u", str(script_path), *(str(arg) for arg in command_args)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                bufsize=1,
            )
            self.processes[run_id] = process
        rendered = " ".join([sys.executable, "-u", str(script_path), *(str(arg) for arg in command_args)])
        self.emit("proc-line", {"runId": run_id, "line": f"$ {rendered}"})

        def read_lines(stream) -> None:
            for line in iter(stream.readline, ""):
                self.emit("proc-line", {"runId": run_id, "line": line.rstrip("\r\n")})
            stream.close()

        def finish() -> None:
            assert process.stdout is not None and process.stderr is not None
            threads = [
                threading.Thread(target=read_lines, args=(process.stdout,), daemon=True),
                threading.Thread(target=read_lines, args=(process.stderr,), daemon=True),
            ]
            for thread in threads:
                thread.start()
            code = process.wait()
            for thread in threads:
                thread.join()
            with self.processes_lock:
                self.processes.pop(run_id, None)
            self.emit("proc-done", {"runId": run_id, "code": code})

        threading.Thread(target=finish, daemon=True).start()

    def cancel_script(self, run_id: str) -> None:
        with self.processes_lock:
            process = self.processes.get(run_id)
        if process and process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                process.terminate()


class Handler(BaseHTTPRequestHandler):
    server: "WebServer"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        print("[http] " + re.sub(r"([?&]token=)[^&\s]+", r"\1[redacted]", fmt % args))

    @property
    def state(self) -> WebState:
        return self.server.state

    def _json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _request_allowed(self) -> None:
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"}:
            raise PermissionError("このサーバーはこのPCからのみ利用できます")
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
            raise PermissionError("別のサイトからのリクエストは受け付けません")

    def _read_body(self) -> bytes:
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_BODY:
            raise ValueError("送信データが大きすぎます")
        return self.rfile.read(size)

    def _auth(self) -> None:
        self._request_allowed()
        self.state.require_token(self.headers.get("X-OpenApi-Token"))

    def do_GET(self) -> None:  # noqa: N802
        parts = urllib.parse.urlsplit(self.path)
        if parts.path == "/api/client-config":
            try:
                self._request_allowed()
                self._json({"token": self.state.token})
            except Exception as error:
                self._json({"error": str(error)}, 403)
            return
        if parts.path == "/api/events":
            try:
                self._request_allowed()
                query = urllib.parse.parse_qs(parts.query)
                self.state.require_token((query.get("token") or [None])[0])
                self._events()
            except Exception as error:
                self._json({"error": str(error)}, 403)
            return
        try:
            self._request_allowed()
            self._static(parts.path)
        except PermissionError as error:
            self._json({"error": str(error)}, 403)

    def _events(self) -> None:
        listener: queue.Queue = queue.Queue(maxsize=2000)
        with self.state.events_lock:
            self.state.events.add(listener)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                try:
                    name, data = listener.get(timeout=15)
                    self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self.state.events_lock:
                self.state.events.discard(listener)

    def _static(self, route: str) -> None:
        relative = urllib.parse.unquote(route.lstrip("/")) or "index.html"
        candidate = (self.state.static_root / relative).resolve()
        if not _inside(candidate, self.state.static_root):
            self._json({"error": "file not found"}, 404)
            return
        if candidate.is_dir():
            candidate /= "index.html"
        if not candidate.is_file():
            self._json({"error": "file not found"}, 404)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"} else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        try:
            self._auth()
            parts = urllib.parse.urlsplit(self.path)
            if parts.path == "/api/invoke":
                payload = json.loads(self._read_body().decode("utf-8"))
                result = self.state.invoke(str(payload.get("command", "")), payload.get("args") or {})
                self._json({"result": result})
            elif parts.path == "/api/upload":
                query = urllib.parse.parse_qs(parts.query)
                raw_name = (query.get("name") or ["upload.dat"])[0]
                name = Path(raw_name.replace("\\", "/")).name
                if not name or name in {".", ".."}:
                    raise ValueError("ファイル名が不正です")
                target_dir = IMPORTS / secrets.token_hex(8)
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / name
                target.write_bytes(self._read_body())
                self._json({"path": str(target)})
            elif parts.path == "/api/save-path":
                payload = json.loads(self._read_body().decode("utf-8"))
                raw_name = str(payload.get("defaultPath") or "config.json").replace("\\", "/").split("/")[-1]
                name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name) or "config.json"
                SAVED.mkdir(parents=True, exist_ok=True)
                self._json({"path": str(SAVED / name)})
            elif parts.path == "/api/directory":
                payload = json.loads(self._read_body().decode("utf-8"))
                raw_name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(payload.get("name") or "output"))
                target = OUTPUT / (raw_name or "output")
                target.mkdir(parents=True, exist_ok=True)
                self._json({"path": str(target)})
            elif parts.path == "/api/open-path":
                payload = json.loads(self._read_body().decode("utf-8"))
                self._download_path(str(payload.get("path", "")))
            else:
                self._json({"error": "not found"}, 404)
        except PermissionError as error:
            self._json({"error": str(error)}, 403)
        except Exception as error:
            self._json({"error": str(error)}, 400)

    def _download_path(self, raw_path: str) -> None:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            self._send_file(path, path.name)
            return
        if path.is_dir():
            temp = tempfile.NamedTemporaryFile(prefix="openapi-test-results-", suffix=".zip", dir=TEMP, delete=False)
            temp.close()
            with zipfile.ZipFile(temp.name, "w", zipfile.ZIP_DEFLATED) as archive:
                for child in path.rglob("*"):
                    if child.is_file():
                        archive.write(child, child.relative_to(path))
            self._send_file(Path(temp.name), f"{path.name or 'results'}.zip")
            Path(temp.name).unlink(missing_ok=True)
            return
        self._json({"error": "指定されたファイルが見つかりません"}, 404)

    def _send_file(self, path: Path, name: str) -> None:
        size = path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as source:
            shutil.copyfileobj(source, self.wfile)


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state: WebState):
        super().__init__(address, Handler)
        self.state = state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--static-root", type=Path, default=ROOT / "gui-tauri/dist")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--smoke-test", action="store_true", help="Verify HTTP startup and Python bridge, then exit")
    args = parser.parse_args()
    root = args.root.resolve()
    if root != ROOT:
        raise SystemExit(f"source root mismatch: expected {ROOT}, got {root}")
    static_root = args.static_root.resolve()
    if not (static_root / "index.html").is_file():
        raise SystemExit("GUI files are not built. Run npm run build in gui-tauri first.")
    DATA.mkdir(parents=True, exist_ok=True)
    for directory in (IMPORTS, SAVED, OUTPUT, TEMP):
        directory.mkdir(parents=True, exist_ok=True)
    state = WebState(static_root)
    server = WebServer(("127.0.0.1", args.port), state)
    url = f"http://127.0.0.1:{server.server_port}/"
    if args.smoke_test:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status != 200 or b"<html" not in response.read().lower():
                    raise RuntimeError("Browser UI did not load")
            payload = json.dumps({"command": "diagnose_runtime", "args": {}}).encode()
            request = urllib.request.Request(url + "api/invoke", data=payload, headers={
                "Content-Type": "application/json", "X-OpenApi-Token": state.token,
            })
            with urllib.request.urlopen(request, timeout=10) as response:
                runtime = json.load(response)["result"]
            if not all(runtime.get(key) for key in ("pythonAvailable", "workflowAvailable", "generatorAvailable", "runnerAvailable")):
                raise RuntimeError(f"Runtime is incomplete: {runtime}")
            print("[smoke] Browser UI and runtime HTTP endpoint started successfully")
            print(json.dumps(runtime))
            # Exercise the same separate Python bridge process used by the UI.
            result = state.invoke("bridge_call", {"command": "list_operations", "args": {
                "path": str(ROOT / "docs/release_candidate_openapi.json"),
            }})
            if not result:
                raise RuntimeError("Python bridge returned no operations")
            print("[smoke] OpenAPI imported through Python bridge")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        return 0
    print(f"[web] Local-only API tester: {url}")
    print("[web] Browser mode avoids building or launching a Tauri exe. Press Ctrl+C to stop.")
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\n[web] Shutting down")
    finally:
        server.server_close()
        with state.processes_lock:
            running = list(state.processes.values())
        for process in running:
            if process.poll() is None:
                process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
