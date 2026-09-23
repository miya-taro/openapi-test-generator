"""実行結果を JUnit XML 形式で出力する。

schemathesis（別CIジョブで実行）の `--junit-xml` 出力や PHPUnit の `--log-junit` 出力と
同じ形式にすることで、言語・ツールをまたいで同じ形式の試験結果報告書生成スクリプトで
扱えるようにする。
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from pathlib import Path

from models import RunResult
from verifier import FAIL, WARN


def write_junit_xml(
    results: list[tuple[RunResult, str, str]],
    output_path: str | Path,
    suite_name: str = "openapi-test-run",
) -> None:
    """runner.py（Layer1: フィールド単位の検証）の実行結果を JUnit XML として書き出す。

    results: [(RunResult, verdict, detail), ...]（excel_writer.write_results と同じ形式）
    """
    testsuite = ET.Element("testsuite", name=suite_name)
    failures = 0
    errors = 0
    total_time = 0.0

    for result, verdict, detail in results:
        elapsed_sec = result.elapsed_ms / 1000
        total_time += elapsed_sec
        classname = f"{result.case.method} {result.case.path}"
        testcase = ET.SubElement(
            testsuite, "testcase",
            classname=classname, name=result.case.id, time=f"{elapsed_sec:.3f}",
        )
        if result.error is not None:
            # トランスポート層のエラー（タイムアウト・接続エラー等）はアサーション失敗とは
            # 区別し、JUnitの慣例に従って <error> として扱う。
            errors += 1
            error_el = ET.SubElement(testcase, "error", message=detail or result.error)
            error_el.text = result.curl_command
        elif verdict == FAIL:
            failures += 1
            failure_el = ET.SubElement(testcase, "failure", message=detail)
            failure_el.text = result.curl_command
        elif verdict == WARN:
            # 警告は失敗扱いにしない（runner.py 本体の終了コードもWARNのみなら2でFAILの1とは
            # 区別している）。<system-out> に詳細を残すのみで <failure>/<error> は付けない。
            system_out = ET.SubElement(testcase, "system-out")
            system_out.text = detail

    testsuite.set("tests", str(len(results)))
    testsuite.set("failures", str(failures))
    testsuite.set("errors", str(errors))
    testsuite.set("time", f"{total_time:.3f}")

    _write(testsuite, output_path)


def write_junit_xml_scenarios(
    rows: list[tuple],
    output_path: str | Path,
    suite_name: str = "openapi-test-db-scenario",
) -> None:
    """db_scenario_runner.py（Layer2: DBシナリオ）の実行結果を JUnit XML として書き出す。

    Accept legacy (name, ok, api_status, detail) and case-ID-aware
    (case_id, name, ok, api_status, detail) rows.
    """
    testsuite = ET.Element("testsuite", name=suite_name)
    failures = 0

    for row in rows:
        if len(row) == 5:
            case_id, scenario_name, ok, api_status, detail = row
        elif len(row) == 4:
            scenario_name, ok, api_status, detail = row
            case_id = scenario_name
        else:
            raise ValueError("DBシナリオ結果の行は4要素または5要素で指定してください")
        testcase = ET.SubElement(
            testsuite, "testcase", classname=suite_name, name=case_id, scenarioName=scenario_name
        )
        if not ok:
            failures += 1
            failure_el = ET.SubElement(testcase, "failure", message=detail)
            failure_el.text = f"API status: {api_status}"

    testsuite.set("tests", str(len(rows)))
    testsuite.set("failures", str(failures))

    _write(testsuite, output_path)


def _write(testsuite: ET.Element, output_path: str | Path) -> None:
    testsuites = ET.Element("testsuites")
    testsuites.append(testsuite)
    tree = ET.ElementTree(testsuites)
    ET.indent(tree, space="  ")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path), encoding="utf-8", xml_declaration=True)
