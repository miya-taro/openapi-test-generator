import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from progress_parser import ProgressTracker


def test_initial_state_zero_percent():
    t = ProgressTracker()
    assert t.percent == 0


def test_detects_total_from_case_count_line():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 196 件")
    assert t.total == 196
    assert t.completed == 0


def test_detects_total_from_scenario_count_line():
    t = ProgressTracker()
    t.feed_line("[INFO] シナリオ数: 3 件")
    assert t.total == 3


def test_counts_result_lines_as_completed():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 4 件")
    t.feed_line("  [OK] TC-op-001 GET /x → 200")
    t.feed_line("  [NG] TC-op-002 GET /x → 500")
    t.feed_line("  [WARNING] TC-op-003 GET /x → 200")
    t.feed_line("  [SKIP] TC-op-004 GET /x → 200")
    assert t.completed == 4
    assert t.percent == 100


def test_percent_is_proportional():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 10 件")
    for _ in range(3):
        t.feed_line("  [OK] TC-x GET /x → 200")
    assert t.percent == 30


def test_unrelated_lines_do_not_affect_progress():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 5 件")
    t.feed_line("INFO OpenAPI パース完了 (version='3.1.0')")
    t.feed_line("$ python runner.py ...")
    assert t.completed == 0


def test_reset_clears_state():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 5 件")
    t.feed_line("  [OK] TC-x GET /x → 200")
    t.reset()
    assert t.total == 0
    assert t.completed == 0
    assert t.percent == 0


def test_new_total_line_resets_completed_count():
    # 「生成して実行」タブでは、生成フェーズと実行フェーズで別々に件数行が出るため、
    # 2回目の件数行が来たら completed をリセットする
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 5 件")
    t.feed_line("  [OK] TC-x GET /x → 200")
    t.feed_line("[INFO] 試験ケース数: 5 件")
    assert t.completed == 0


def test_percent_never_exceeds_100_even_with_more_lines_than_total():
    t = ProgressTracker()
    t.feed_line("[INFO] 試験ケース数: 2 件")
    for _ in range(5):
        t.feed_line("  [OK] TC-x GET /x → 200")
    assert t.percent == 100
