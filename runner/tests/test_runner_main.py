"""runner.py の main() 自体のオーケストレーション（引数検証・呼び出し配線・
--fail-fast / --full-body の分岐など）を in-process で検証する。

http_client / hook_runner / config_loader / excel_reader / excel_writer は
それぞれ専用のユニットテストで検証済みのため、ここでは全てフェイクに差し替え、
runner.py の main() が「何を・どの順番で・どんな引数で」呼ぶかだけを検証する。
"""
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import runner as runner_module
from models import RunCase, RunResult

MINIMAL_OPENAPI = {"openapi": "3.1.0", "paths": {}}


def _case(id_="TC-op-001", status="200") -> RunCase:
    return RunCase(
        id=id_,
        operation_id="op",
        path="/x",
        method="GET",
        param_in="query",
        param_name="p",
        input_value="1",
        expected_status=status,
        expected_response_body="",
        expected_response_header="",
        expected_response_time="3秒以内",
        expected_result="",
    )


def _write_files(tmp_path) -> tuple[Path, Path]:
    excel_path = tmp_path / "spec.xlsx"
    excel_path.write_bytes(b"dummy")  # read_excel はフェイクに差し替えるので中身は不問
    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(MINIMAL_OPENAPI), encoding="utf-8")
    return excel_path, openapi_path


def _patch_happy_path(monkeypatch, cases=None, status=200, calls=None):
    """健全系の一連のフェイクを仕込む。calls が渡されれば呼び出し記録を残す。"""
    calls = calls if calls is not None else []
    cases = cases if cases is not None else [_case()]

    monkeypatch.setattr(runner_module, "read_excel", lambda path: cases)
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        calls.append(("execute", case.id))
        return RunResult(
            case=case, actual_status=status, actual_body="{}",
            actual_headers={}, elapsed_ms=10.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)

    def fake_write_results(excel_path, results, output_path, full_body=False):
        calls.append(("write_results", len(results), full_body))
        Path(output_path).write_bytes(b"")

    monkeypatch.setattr(runner_module, "write_results", fake_write_results)
    return calls


def run_main(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", ["runner.py", *argv])
    return runner_module.main()


# --- 引数検証: --setup/--teardown には --config が必須 ---


def test_setup_without_config_returns_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x", "--setup", "s.sql"])
    assert code == 4


def test_teardown_without_config_returns_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    code = run_main(
        monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x", "--teardown", "t.sql"]
    )
    assert code == 4


def test_setup_with_config_does_not_return_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch)
    monkeypatch.setattr(runner_module, "load_config", lambda path: {"postgres": {"host": "h"}})
    monkeypatch.setattr(runner_module, "get_postgres_config", lambda config: config["postgres"])
    monkeypatch.setattr(runner_module, "run_hook", lambda *a, **k: None)
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x",
         "--setup", "s.sql", "--config", "c.json"],
    )
    assert code != 4


# --- 存在確認系 ---


def test_missing_excel_file_returns_3(monkeypatch, tmp_path):
    code = run_main(
        monkeypatch,
        [str(tmp_path / "nope.xlsx"), str(tmp_path / "nope.json"), "--base-url", "http://x"],
    )
    assert code == 3


# --- setup/teardown フックの呼び出し配線 ---


def test_setup_and_teardown_hooks_called_with_correct_args_and_order(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    calls = _patch_happy_path(monkeypatch)
    monkeypatch.setattr(runner_module, "load_config", lambda path: {"postgres": {"host": "h", "dbname": "d"}})
    monkeypatch.setattr(runner_module, "get_postgres_config", lambda config: config["postgres"])

    def fake_run_hook(sql_path, db_config, is_teardown=False):
        calls.append(("run_hook", sql_path, is_teardown))

    monkeypatch.setattr(runner_module, "run_hook", fake_run_hook)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x",
         "--setup", "setup.sql", "--teardown", "teardown.sql", "--config", "c.json"],
    )

    assert code == 0
    kinds = [c[0] for c in calls]
    # setup → execute → teardown → write_results の順で呼ばれること
    assert kinds.index("run_hook") < kinds.index("execute")
    setup_call = next(c for c in calls if c[0] == "run_hook" and c[2] is False)
    teardown_call = next(c for c in calls if c[0] == "run_hook" and c[2] is True)
    assert setup_call[1] == "setup.sql"
    assert teardown_call[1] == "teardown.sql"
    assert kinds.index("execute") < kinds.index("run_hook", kinds.index("run_hook") + 1)


def test_teardown_still_runs_when_status_check_fails(monkeypatch, tmp_path):
    # NG（ステータス不一致）が出ても teardown は必ず実行される
    excel_path, openapi_path = _write_files(tmp_path)
    calls = _patch_happy_path(monkeypatch, cases=[_case(status="200")], status=500)
    monkeypatch.setattr(runner_module, "load_config", lambda path: {"postgres": {"host": "h"}})
    monkeypatch.setattr(runner_module, "get_postgres_config", lambda config: config["postgres"])

    def fake_run_hook(sql_path, db_config, is_teardown=False):
        calls.append(("run_hook", sql_path, is_teardown))

    monkeypatch.setattr(runner_module, "run_hook", fake_run_hook)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x",
         "--teardown", "teardown.sql", "--config", "c.json"],
    )
    assert code == 1  # NG があるので終了コード1
    assert any(c[0] == "run_hook" and c[2] is True for c in calls)


# --- --fail-fast ---


def test_fail_fast_stops_after_first_failure(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case("TC-op-001"), _case("TC-op-002"), _case("TC-op-003")]
    calls = _patch_happy_path(monkeypatch, cases=cases, status=500)  # 全件ステータス不一致でNG

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--fail-fast"],
    )
    assert code == 1
    executed = [c for c in calls if c[0] == "execute"]
    assert len(executed) == 1  # 1件目のNGで打ち切られる


def test_without_fail_fast_all_cases_executed_despite_failures(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case("TC-op-001"), _case("TC-op-002"), _case("TC-op-003")]
    calls = _patch_happy_path(monkeypatch, cases=cases, status=500)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 1
    executed = [c for c in calls if c[0] == "execute"]
    assert len(executed) == 3


def test_case_ids_runs_only_selected_contract_cases(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case("TC-op-001"), _case("TC-op-002")]
    calls = _patch_happy_path(monkeypatch, cases=cases)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--case-ids", "TC-op-002"],
    )

    assert code == 0
    assert [call[1] for call in calls if call[0] == "execute"] == ["TC-op-002"]


def test_case_ids_reject_unknown_contract_case(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch, cases=[_case("TC-op-001")])

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--case-ids", "TC-missing"],
    )

    assert code == 4


# --- --parallel ---


def test_parallel_zero_returns_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "0"],
    )
    assert code == 4


def test_parallel_negative_returns_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "-1"],
    )
    assert code == 4


def test_parallel_executes_all_cases_and_writes_all_results(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case(f"TC-op-{i:03d}") for i in range(1, 11)]
    calls = _patch_happy_path(monkeypatch, cases=cases, status=200)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "4"],
    )
    assert code == 0
    executed = [c for c in calls if c[0] == "execute"]
    assert len(executed) == 10
    assert {c[1] for c in executed} == {case.id for case in cases}  # 全ケースが重複・欠落なく実行される
    write_call = next(c for c in calls if c[0] == "write_results")
    assert write_call[1] == 10  # 結果件数もケース数と一致する


def test_parallel_detects_failures_and_returns_1(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case(f"TC-op-{i:03d}") for i in range(1, 6)]
    _patch_happy_path(monkeypatch, cases=cases, status=500)  # 全件NG

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "3"],
    )
    assert code == 1


def test_parallel_with_fail_fast_does_not_crash_and_reports_failure(monkeypatch, tmp_path):
    # 並列実行下での --fail-fast は「最初のNGを検出した時点」より後ろにずれる概算のため、
    # 停止した正確な実行件数までは断定しない。配線が壊れていないことのみ検証する。
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case(f"TC-op-{i:03d}") for i in range(1, 11)]
    calls = _patch_happy_path(monkeypatch, cases=cases, status=500)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "2", "--fail-fast"],
    )
    assert code == 1
    executed = [c for c in calls if c[0] == "execute"]
    assert 1 <= len(executed) <= 10
    write_call = next(c for c in calls if c[0] == "write_results")
    assert write_call[1] == len(executed)  # 書き出す結果件数は実際に実行した件数と一致する


# --- --cookie-jar ---


def test_cookie_jar_with_parallel_returns_4(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x",
         "--cookie-jar", "--parallel", "2"],
    )
    assert code == 4


def test_cookie_jar_flag_shares_session_with_cookie_persistence(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    seen = []

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        seen.append((session, persist_cookies))
        return RunResult(
            case=case, actual_status=200, actual_body="{}",
            actual_headers={}, elapsed_ms=1.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--cookie-jar"],
    )
    assert code == 0
    assert len(seen) == 1
    session, persist_cookies = seen[0]
    assert isinstance(session, requests.Session)
    assert persist_cookies is True


def test_without_cookie_jar_flag_session_shared_but_not_persisted(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    seen = []

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        seen.append((session, persist_cookies))
        return RunResult(
            case=case, actual_status=200, actual_body="{}",
            actual_headers={}, elapsed_ms=1.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 0
    session, persist_cookies = seen[0]
    assert isinstance(session, requests.Session)  # コネクションプーリングのため常に共有される
    assert persist_cookies is False


def test_parallel_flag_widens_connection_pool_to_match(monkeypatch, tmp_path):
    # urllib3の既定pool_maxsizeは10なので、--parallelがそれを超える場合は
    # プールが枯渇して並列度が頭打ちにならないよう、プールサイズを引き上げる必要がある。
    excel_path, openapi_path = _write_files(tmp_path)
    cases = [_case(f"TC-op-{i:03d}") for i in range(1, 21)]
    seen = []

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        seen.append(session)
        return RunResult(
            case=case, actual_status=200, actual_body="{}",
            actual_headers={}, elapsed_ms=1.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "read_excel", lambda path: cases)
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--parallel", "20"],
    )
    assert code == 0
    session = seen[0]
    adapter = session.get_adapter("http://x")
    assert adapter._pool_maxsize >= 20


def test_default_parallel_keeps_standard_pool_size(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    seen = []

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        seen.append(session)
        return RunResult(
            case=case, actual_status=200, actual_body="{}",
            actual_headers={}, elapsed_ms=1.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 0
    session = seen[0]
    adapter = session.get_adapter("http://x")
    assert adapter._pool_maxsize == 10


# --- --junit-xml ---


def test_junit_xml_flag_writes_file(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch)
    junit_path = tmp_path / "result.xml"

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--junit-xml", str(junit_path)],
    )
    assert code == 0
    assert junit_path.exists()


def test_without_junit_xml_flag_no_file_written(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 0
    assert not (tmp_path / "result.xml").exists()


# --- --full-body ---


def test_full_body_flag_threaded_to_write_results(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    calls = _patch_happy_path(monkeypatch)

    run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x", "--full-body"])
    write_call = next(c for c in calls if c[0] == "write_results")
    assert write_call[2] is True  # full_body=True で渡っている


def test_full_body_default_false(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    calls = _patch_happy_path(monkeypatch)

    run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    write_call = next(c for c in calls if c[0] == "write_results")
    assert write_call[2] is False


# --- 終了コード: 全件OK / WARNのみ ---


def test_all_pass_returns_0(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch, status=200)
    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 0


def test_health_check_failure_returns_3(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: False)
    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 3


def test_skip_health_check_bypasses_a_failing_health_check(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch)
    monkeypatch.setattr(
        runner_module, "health_check",
        lambda base_url, health_path: (_ for _ in ()).throw(AssertionError("health_check should not be called")),
    )
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--skip-health-check"],
    )
    assert code == 0


# --- openapi.json 読み込み: 警告のみで続行 ---


def test_missing_openapi_file_warns_and_continues(monkeypatch, tmp_path, capsys):
    excel_path = tmp_path / "spec.xlsx"
    excel_path.write_bytes(b"dummy")
    missing_openapi = tmp_path / "does_not_exist.json"
    _patch_happy_path(monkeypatch)

    code = run_main(monkeypatch, [str(excel_path), str(missing_openapi), "--base-url", "http://x"])
    assert code == 0
    assert "openapi.json が見つかりません" in capsys.readouterr().err


def test_invalid_openapi_warns_and_continues(monkeypatch, tmp_path, capsys):
    excel_path = tmp_path / "spec.xlsx"
    excel_path.write_bytes(b"dummy")
    bad_openapi = tmp_path / "bad.json"
    bad_openapi.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    _patch_happy_path(monkeypatch)

    code = run_main(monkeypatch, [str(excel_path), str(bad_openapi), "--base-url", "http://x"])
    assert code == 0
    assert "openapi.json の読み込みに失敗しました" in capsys.readouterr().err


# --- Excel 読み込みエラー ---


def test_excel_read_error_returns_3(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)

    def raise_error(path):
        raise ValueError("broken workbook")

    monkeypatch.setattr(runner_module, "read_excel", raise_error)
    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 3


# --- dry-run ---


def test_dry_run_returns_0_without_executing(monkeypatch, tmp_path, capsys):
    excel_path, openapi_path = _write_files(tmp_path)
    calls = _patch_happy_path(monkeypatch)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x", "--dry-run"])
    assert code == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert not any(c[0] == "execute" for c in calls)


# --- config.json 読み込みエラー ---


def test_config_load_error_returns_3(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])

    def raise_value_error(path):
        raise ValueError("db セクションがありません")

    monkeypatch.setattr(runner_module, "load_config", raise_value_error)
    monkeypatch.setattr(runner_module, "run_hook", lambda *a, **k: None)
    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x",
         "--setup", "s.sql", "--config", "bad_config.json"],
    )
    assert code == 3


# --- 結果 Excel 書き込みエラー ---


def test_write_results_error_returns_3(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(
        runner_module, "execute_with_openapi",
        lambda case, base_url, openapi, session=None, persist_cookies=False: RunResult(
            case=case, actual_status=200, actual_body="{}", actual_headers={}, elapsed_ms=1.0, exit_code=0
        ),
    )

    def raise_error(excel_path, results, output_path, full_body=False):
        raise PermissionError("cannot write")

    monkeypatch.setattr(runner_module, "write_results", raise_error)
    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 3


# --- WARN のみの場合は終了コード2 ---


def test_warn_only_returns_2(monkeypatch, tmp_path):
    excel_path, openapi_path = _write_files(tmp_path)
    # ステータスは一致させ、応答時間だけ超過させて WARN のみを発生させる
    case = _case(status="200")
    monkeypatch.setattr(runner_module, "read_excel", lambda path: [case])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(
        runner_module, "execute_with_openapi",
        lambda c, base_url, openapi, session=None, persist_cookies=False: RunResult(
            case=c, actual_status=200, actual_body="{}", actual_headers={}, elapsed_ms=99999.0, exit_code=0
        ),
    )
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)

    code = run_main(monkeypatch, [str(excel_path), str(openapi_path), "--base-url", "http://x"])
    assert code == 2


# --- --auth-config ---


def test_auth_config_login_failure_returns_3(monkeypatch, tmp_path):
    # main() は os.environ を直接書き換える。setenv でダミー値を挟むことで
    # 「元は未設定だった」ことを monkeypatch に記録させ、テスト終了時に確実に削除させる
    # （delenv(raising=False) はキーが元々存在しない場合は何も記録しないため不十分）。
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "__placeholder__")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "__placeholder__")
    excel_path, openapi_path = _write_files(tmp_path)
    _patch_happy_path(monkeypatch)

    def raise_auth_error(base_url, auth_cfg, session=None):
        raise runner_module.AuthLoginError("ログイン失敗")

    monkeypatch.setattr(runner_module, "load_auth_config", lambda path: {"login_url": "/login", "method": "POST"})
    monkeypatch.setattr(runner_module, "perform_login", raise_auth_error)

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--auth-config", "auth.json"],
    )
    assert code == 3


def test_auth_config_success_sets_env_before_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_AUTH_HEADER_NAME", "__placeholder__")
    monkeypatch.setenv("TEST_AUTH_HEADER_VALUE", "__placeholder__")
    excel_path, openapi_path = _write_files(tmp_path)
    calls = []
    seen_env = {}

    def fake_execute(case, base_url, openapi, session=None, persist_cookies=False):
        import os
        seen_env["name"] = os.environ.get("TEST_AUTH_HEADER_NAME")
        seen_env["value"] = os.environ.get("TEST_AUTH_HEADER_VALUE")
        calls.append(("execute", case.id))
        return RunResult(
            case=case, actual_status=200, actual_body="{}",
            actual_headers={}, elapsed_ms=10.0, exit_code=0,
        )

    monkeypatch.setattr(runner_module, "read_excel", lambda path: [_case()])
    monkeypatch.setattr(runner_module, "health_check", lambda base_url, health_path: True)
    monkeypatch.setattr(runner_module, "execute_with_openapi", fake_execute)
    monkeypatch.setattr(runner_module, "write_results", lambda *a, **k: None)
    monkeypatch.setattr(runner_module, "load_auth_config", lambda path: {"login_url": "/login", "method": "POST"})
    monkeypatch.setattr(runner_module, "perform_login", lambda base_url, auth_cfg, session=None: "tok123")

    code = run_main(
        monkeypatch,
        [str(excel_path), str(openapi_path), "--base-url", "http://x", "--auth-config", "auth.json"],
    )
    assert code == 0
    assert seen_env["name"] == "Authorization"
    assert seen_env["value"] == "Bearer tok123"
