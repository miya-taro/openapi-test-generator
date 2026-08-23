import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from process_runner import run_streamed, exit_code_meaning


def test_exit_code_meaning_known_codes():
    assert "OK" in exit_code_meaning(0)
    assert "NG" in exit_code_meaning(1)
    assert "WARNING" in exit_code_meaning(2)


def test_exit_code_meaning_unknown_code_falls_back_to_raw_code():
    assert exit_code_meaning(99) == "終了コード 99"


def test_run_streamed_real_subprocess_captures_output_and_exit_code():
    log_queue: queue.Queue = queue.Queue()
    cmd = [sys.executable, "-c", "print('line1'); print('line2')"]

    code = run_streamed(cmd, log_queue)

    assert code == 0
    lines = []
    while not log_queue.empty():
        lines.append(log_queue.get_nowait())
    texts = [item[1] for item in lines if item[0] == "line"]
    assert any("line1" in t for t in texts)
    assert any("line2" in t for t in texts)


def test_run_streamed_real_subprocess_nonzero_exit_code():
    log_queue: queue.Queue = queue.Queue()
    cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]

    code = run_streamed(cmd, log_queue)

    assert code == 3


def test_run_streamed_calls_on_start_with_popen_object():
    log_queue: queue.Queue = queue.Queue()
    cmd = [sys.executable, "-c", "print('x')"]
    captured = []

    code = run_streamed(cmd, log_queue, on_start=lambda proc: captured.append(proc))

    assert code == 0
    assert len(captured) == 1
    assert captured[0].pid > 0


def test_run_streamed_on_start_not_called_when_process_fails_to_launch():
    log_queue: queue.Queue = queue.Queue()
    cmd = ["this-command-does-not-exist-12345"]
    captured = []

    run_streamed(cmd, log_queue, on_start=lambda proc: captured.append(proc))

    assert captured == []


def test_run_streamed_terminated_process_returns_nonzero_and_stops_early(monkeypatch):
    """on_start経由でハンドルを受け取り、途中でterminate()した場合の挙動を確認する
    （GUI側のキャンセル機能が使う経路）。"""
    log_queue: queue.Queue = queue.Queue()
    cmd = [sys.executable, "-c", "import time; [print(i) or time.sleep(0.05) for i in range(100)]"]

    def on_start(proc):
        proc.terminate()

    code = run_streamed(cmd, log_queue, on_start=on_start)

    assert code != 0


def test_run_streamed_missing_executable_returns_negative_one():
    log_queue: queue.Queue = queue.Queue()
    cmd = ["this-command-does-not-exist-12345"]

    code = run_streamed(cmd, log_queue)

    assert code == -1
    lines = [item for item in list(log_queue.queue) if item[0] == "line"]
    assert any("失敗" in item[1] for item in lines)
