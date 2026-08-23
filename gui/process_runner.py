"""サブプロセスの標準出力を1行ずつキューに流すヘルパー（バックグラウンドスレッドから使う）。"""
from __future__ import annotations
import queue
import subprocess
from typing import Callable

EXIT_CODE_MEANINGS: dict[int, str] = {
    0: "OK：全ケース成功",
    1: "NG：1件以上失敗",
    2: "WARNING：1件以上警告（応答時間超過）",
    3: "ERROR：実行エラー",
    4: "ERROR：設定エラー",
}


def exit_code_meaning(code: int) -> str:
    return EXIT_CODE_MEANINGS.get(code, f"終了コード {code}")


def run_streamed(
    cmd: list[str], log_queue: "queue.Queue[tuple]",
    on_start: "Callable[[subprocess.Popen], None] | None" = None,
) -> int:
    """コマンドを実行し、標準出力/標準エラーを1行ずつ ("line", text) として log_queue に流す。

    on_start が指定されていれば、プロセス起動直後（Popenオブジェクトを渡して）呼び出す。
    GUI側がプロセスハンドルを保持してキャンセルできるようにするためのフック。

    戻り値は終了コード（起動自体に失敗した場合は -1）。
    """
    log_queue.put(("line", "$ " + " ".join(cmd)))
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as e:
        log_queue.put(("line", f"[ERROR] コマンド起動に失敗しました: {e}"))
        return -1

    if on_start:
        on_start(proc)

    assert proc.stdout is not None
    for line in proc.stdout:
        log_queue.put(("line", line.rstrip("\n")))
    proc.wait()
    return proc.returncode
