"""runner.py / db_scenario_runner.py の標準出力から進捗（総数・完了数）を読み取る。

GUI表示用の付随機能であり、パースに失敗しても実行結果自体には影響しない
（進捗0%のまま表示されるだけ）。
"""
from __future__ import annotations
import re

_TOTAL_PATTERN = re.compile(r"(?:試験ケース数|シナリオ数)[：:]\s*(\d+)\s*件")
_RESULT_LINE_PATTERN = re.compile(r"^\s*\[(OK|NG|WARNING|SKIP)\]")


class ProgressTracker:
    def __init__(self) -> None:
        self.total = 0
        self.completed = 0

    def reset(self) -> None:
        self.total = 0
        self.completed = 0

    def feed_line(self, line: str) -> None:
        m = _TOTAL_PATTERN.search(line)
        if m:
            self.total = int(m.group(1))
            self.completed = 0
            return
        if _RESULT_LINE_PATTERN.match(line):
            self.completed += 1

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return max(0, min(100, int(self.completed / self.total * 100)))
