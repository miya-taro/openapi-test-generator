#!/usr/bin/env python3
"""Run a reviewed JSON plan with pytest and project its results to reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runner"))
sys.path.insert(1, str(ROOT))

from config_loader import get_postgres_config, load_config
from db_scenario_runner import _contains_response_placeholder
from db_scenario import ScenarioError
from execution_plan import contract_case, contract_raw, load_plan
from http_client import health_check
from models import RunResult
from src.db_scope import scopes_for_case
from src.renderer.excel_output import write_excel_output
from src.renderer.json_output import build_output
from workflow.case_master import CaseMasterError


def _parser():
    parser = argparse.ArgumentParser(description="保存した試験定義をpytestで実行します（Excelは出力専用）")
    parser.add_argument("master", help="case-master.json")
    parser.add_argument("--kind", choices=["contract", "db-scenario"], required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--config")
    parser.add_argument("--auth-config")
    parser.add_argument("--output", "--report-output", dest="output", required=True)
    parser.add_argument("--spec-output")
    parser.add_argument("--evidence-output")
    parser.add_argument("--junit-xml", required=True)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--cookie-jar", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--full-body", action="store_true")
    parser.add_argument("--case-ids")
    parser.add_argument("--setup")
    parser.add_argument("--teardown")
    parser.add_argument("--skip-health-check", action="store_true")
    parser.add_argument("--health-path", default="/health")
    return parser


def _hook(path, config):
    """Strict hooks: always close/rollback, and never swallow a cleanup failure."""
    import psycopg2
    from hook_runner import _split_statements

    sql = Path(path).read_text(encoding="utf-8")
    connection = psycopg2.connect(**get_postgres_config(config))
    try:
        with connection:
            with connection.cursor() as cursor:
                for statement in _split_statements(sql):
                    cursor.execute(statement)
    finally:
        connection.close()


def _preflight(args, cases, api):
    if args.parallel < 1:
        raise ValueError("並列数は1以上で指定してください")
    guarded = any(scopes_for_case(api, contract_case(case)) for case in cases) if args.kind == "contract" else False
    if args.parallel > 1 and (args.cookie_jar or guarded or args.kind == "db-scenario"):
        raise ValueError("Cookie維持・DB照合・シナリオ試験は逐次実行が必要です")
    if (guarded or args.kind == "db-scenario" or args.setup or args.teardown) and not args.config:
        raise ValueError("DB接続設定が必要です")
    if args.case_ids and args.kind == "db-scenario" and any(
        _contains_response_placeholder(case["definition"]) for case in cases
    ):
        raise ValueError("直前のresponseに依存するケースは単独再実行できません")
    if any(case["definition"].get("authProfile") for case in cases) and not args.auth_config:
        raise ValueError("認証プロファイルを使う試験には認証設定が必要です")
    for path in (args.setup, args.teardown):
        if path and not Path(path).is_file():
            raise ValueError("準備・後片付けSQLファイルが見つかりません")


def _run_pytest(args, options, temp):
    config_path = temp / "pytest.ini"
    config_path.write_text("[pytest]\n", encoding="utf-8")
    options_path = temp / "options.json"
    options_path.write_text(json.dumps(options, ensure_ascii=False), encoding="utf-8")
    command = [sys.executable, str(ROOT / "runner" / "pytest_entry.py"), "-p", "pytest_runtime",
               str(ROOT / "runner" / "runtime_suite.py"), "--noconftest", "-c", str(config_path),
               "--rootdir", str(temp), "-p", "no:cacheprovider", "--tb=no", "--show-capture=no",
               "-o", "junit_logging=no", "-o", "junit_log_passing_tests=false", "-q",
               "--junitxml", str(Path(args.junit_xml).resolve())]
    if args.parallel > 1:
        command.extend(["-p", "xdist.plugin", "-n", str(args.parallel), "--max-worker-restart=0"])
    if args.fail_fast:
        command.append("-x")
    env = os.environ.copy()
    # No unrelated project conftest, user addopts, or third-party auto-loaded plugins.
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS"):
        env.pop(name, None)
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([str(ROOT / "runner"), str(ROOT)]),
               OTG_EXECUTION_OPTIONS=str(options_path))
    return subprocess.run(command, cwd=temp, env=env, check=False).returncode


def _records(cases, directory):
    rows = []
    for case in cases:
        name = hashlib.sha256(case["caseId"].encode("utf-8")).hexdigest() + ".json"
        path = directory / name
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("definitionHash") != case["definitionHash"] or row.get("caseId") != case["caseId"]:
                raise ValueError("実行結果と試験定義が一致しません")
        else:
            row = {"caseId": case["caseId"], "kind": case["kind"], "definitionHash": case["definitionHash"],
                   "status": "not-run", "verdict": "未実施", "actualStatus": 0,
                   "detail": "実行されていません（途中停止・準備失敗など）"}
        rows.append(row)
    return rows


def _complete_junit(path, cases, records, run_errors):
    """Native pytest JUnit, augmented only for unstarted cases and run-level errors."""
    path = Path(path)
    root = ET.parse(path).getroot() if path.is_file() else ET.Element("testsuites")
    present = {item.get("name") for item in root.iter("testcase")}
    missing = [case for case in cases if case["caseId"] not in present]
    if missing or run_errors:
        suite = ET.SubElement(root, "testsuite", name="execution-completeness",
                              tests=str(len(missing) + len(run_errors)), errors=str(len(run_errors)),
                              skipped=str(len(missing)), failures="0")
        for case in missing:
            item = ET.SubElement(suite, "testcase", name=case["caseId"], classname="not-run")
            ET.SubElement(item, "skipped", message="未実施：試験を開始できませんでした")
        for index, message in enumerate(run_errors):
            item = ET.SubElement(suite, "testcase", name=f"RUN-ERROR-{index + 1}", classname="execution")
            ET.SubElement(item, "error", message=message)
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _reports(args, master, cases, api, records, run_errors):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_json = output.with_suffix(".json")
    result_json.write_text(json.dumps({"format": "api-tester.execution-result", "schemaVersion": 1,
                                      "engine": "pytest", "cases": records, "runErrors": run_errors},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    _complete_junit(args.junit_xml, cases, records, run_errors)
    if args.kind == "contract":
        from excel_writer import write_results
        spec_path = Path(args.spec_output) if args.spec_output else output.with_name("test-spec.xlsx")
        raw = build_output([contract_raw(case) for case in cases], str(args.master))
        raw["coverage"] = master.get("coverage", [])
        write_excel_output(raw, str(spec_path), api, args.base_url)
        results = []
        for case, row in zip(cases, records, strict=True):
            if row["status"] == "not-run":
                continue
            result = RunResult(contract_case(case), row.get("actualStatus", 0), row.get("body", ""),
                               row.get("headers", {}), row.get("elapsedMs", 0), 0,
                               row.get("curl", ""), row.get("error"), row.get("body"), row.get("request", {}))
            results.append((result, row["verdict"], row["detail"]))
        write_results(spec_path, results, output, full_body=args.full_body)
        evidence = [item for row in records for item in row.get("dbEvidence", [])]
        if evidence:
            output.with_name(output.stem + "-db-evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        from db_scenario_report import write_report
        rows = [(case["caseId"], case["title"], row["verdict"], row.get("actualStatus", 0), row["detail"])
                for case, row in zip(cases, records, strict=True)]
        evidence = [row["evidence"] for row in records if "evidence" in row]
        write_report(rows, output, evidence)
        if args.evidence_output:
            Path(args.evidence_output).write_text(json.dumps({"cases": evidence}, ensure_ascii=False, indent=2), encoding="utf-8")
    if run_errors:
        # A successful HTTP assertion must not hide a failed run-level teardown.
        import openpyxl
        from report_layout import safe_cell
        workbook = openpyxl.load_workbook(output)
        sheet = workbook.create_sheet("実行エラー", 0)
        sheet.append(["試験の実行を正常に完了できませんでした"])
        for message in run_errors:
            sheet.append([safe_cell(message)])
        sheet.column_dimensions["A"].width = 100
        workbook.active = 0
        workbook.save(output)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        ids = tuple(value.strip() for value in args.case_ids.split(",") if value.strip()) if args.case_ids else ()
        if args.case_ids and not ids:
            raise ValueError("試験IDを指定してください")
        master, cases, api = load_plan(args.master, args.kind, ids)
        _preflight(args, cases, api)
        db_config = load_config(args.config) if args.config else {}
    except (CaseMasterError, ScenarioError, OSError, ValueError, KeyError, TypeError):
        print("[ERROR] 実行定義・対象ケース・接続設定を確認し、必要ならケースを再準備してください", file=sys.stderr)
        return 3
    print(f"[INFO] pytestで実行する試験ケース数: {len(cases)} 件")
    if args.dry_run:
        print("[DRY-RUN] 定義を検証しました。HTTP送信・ログイン・DB接続は行っていません")
        return 0
    run_errors = []
    code = 3
    with tempfile.TemporaryDirectory(prefix="api-pytest-") as directory:
        temp = Path(directory)
        records_dir = temp / "records"
        records_dir.mkdir()
        snapshot = temp / "case-master.json"
        snapshot.write_text(json.dumps(master, ensure_ascii=False), encoding="utf-8")
        options = vars(args).copy()
        options.update(master=str(snapshot), records=str(records_dir), case_ids=ids)
        for key in ("config", "auth_config"):
            if options[key]:
                options[key] = str(Path(options[key]).resolve())
        # Never reuse JUnit/results left over from a previous attempt in this run directory.
        Path(args.junit_xml).unlink(missing_ok=True)
        started_setup = False
        try:
            if not args.skip_health_check and not health_check(args.base_url, args.health_path):
                raise ValueError("health check failed")
            started_setup = True
            if args.setup:
                _hook(args.setup, db_config)
            code = _run_pytest(args, options, temp)
            if code not in (0, 1):
                run_errors.append("pytest実行を完了できませんでした（実行基盤・収集・中断エラー）")
        except Exception:
            run_errors.append("接続確認・準備・実行に失敗しました。接続設定とSQLを確認してください")
        finally:
            if started_setup and args.teardown:
                try:
                    _hook(args.teardown, db_config)
                except Exception:
                    run_errors.append("後片付けに失敗しました。試験データが残っている可能性があります")
        records = _records(cases, records_dir)
        try:
            _reports(args, master, cases, api, records, run_errors)
        except Exception:
            print("[ERROR] 結果レポートを作成できませんでした", file=sys.stderr)
            return 3
    if run_errors:
        return 3
    if any(row["status"] in ("error", "failed") for row in records) or code == 1:
        return 1
    if any(row["status"] != "passed" for row in records):
        return 2
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
