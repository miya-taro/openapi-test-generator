"""Build a local HTML report from the reviewed case master and JUnit evidence."""
from __future__ import annotations

from src.db_coverage import execution_summary
import html
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from workflow.case_master import load_case_master

_STATUS_LABELS = {
    "passed": "OK",
    "failed": "NG",
    "error": "ERROR",
    "warning": "WARNING",
    "skipped": "未確認",
    "not-run": "未実行",
}


def _junit_statuses(paths: list[str | Path]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for path in paths:
        source = Path(path)
        if not source.is_file():
            continue
        try:
            root = ET.parse(source).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ValueError(f"JUnit XMLを読み込めません: {source}: {exc}") from exc
        for testcase in root.iter("testcase"):
            case_id = testcase.get("name") or testcase.get("caseId")
            if not case_id:
                continue
            if testcase.find("error") is not None:
                status = "error"
            elif testcase.find("failure") is not None:
                status = "failed"
            elif testcase.find("skipped") is not None:
                status = "skipped"
            elif testcase.find("system-out") is not None:
                status = "warning"
            else:
                status = "passed"
            statuses[case_id] = status
    return statuses


def write_failed_case_ids(junit_paths: list[str | Path], output_path: str | Path) -> list[str]:
    failed: list[str] = []
    for path in junit_paths:
        source = Path(path)
        if not source.is_file():
            continue
        try:
            root = ET.parse(source).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ValueError(f"JUnit XMLを読み込めません: {source}: {exc}") from exc
        for testcase in root.iter("testcase"):
            if testcase.find("failure") is None and testcase.find("error") is None:
                continue
            case_id = testcase.get("name") or testcase.get("caseId")
            if case_id and case_id not in failed:
                failed.append(case_id)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return failed


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def write_html_report(
    case_master_path: str | Path,
    junit_paths: list[str | Path],
    output_path: str | Path,
    artifacts: dict[str, str | Path] | None = None,
) -> None:
    master = load_case_master(case_master_path)
    statuses = _junit_statuses(junit_paths)
    cases = master["cases"]
    unapproved = [
        case for case in cases
        if case["caseId"] in statuses and case.get("reviewStatus", "draft") != "approved"
    ]
    run_statuses = [statuses.get(case["caseId"], "not-run") for case in cases]
    counts = {status: run_statuses.count(status) for status in _STATUS_LABELS}
    approval_text = "探索実行（未承認の試験仕様を含みます）" if unapproved else "承認済み試験仕様"

    links = []
    for label, path in (artifacts or {}).items():
        filename = Path(path).name
        links.append(
            f'<a href="{quote(filename)}">{_e(label)}</a>'
        )
    link_html = "".join(f"<li>{link}</li>" for link in links)

    rows = []
    for case, status in zip(cases, run_statuses, strict=True):
        kind = "Layer 1" if case.get("kind") == "contract" else "Layer 2（DB）"
        review = case.get("reviewStatus", "draft")
        rows.append(
            "<tr>"
            f"<td>{_e(case.get('caseId'))}</td>"
            f"<td>{_e(kind)}</td>"
            f"<td>{_e(case.get('title'))}</td>"
            f"<td class=\"status-{_e(status)}\">{_e(_STATUS_LABELS[status])}</td>"
            f"<td>{_e(review)}</td>"
            "</tr>"
        )
    summary = "　".join(
        f"{_e(_STATUS_LABELS[key])}: {counts[key]}" for key in _STATUS_LABELS if counts[key]
    ) or "ケースなし"
    coverage_rows = "".join(
        "<tr>" + "".join(f"<td>{_e(row.get(key, ''))}</td>" for key in
                         ("operationId", "location", "field", "keyword", "status", "detail")) + f"<td>{_e(execution_summary(row, statuses))}</td></tr>"
        for row in master.get("coverage", [])
    )
    coverage_html = ("<details><summary>仕様の対応状況（実行済み・合格を意味しません）</summary>"
                     "<table><thead><tr><th>API操作</th><th>場所</th><th>項目</th><th>制約</th><th>対応状況</th><th>補足</th><th>今回の実行状況</th></tr></thead>"
                     f"<tbody>{coverage_rows}</tbody></table></details>") if coverage_rows else ""

    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>API試験結果 - {_e(master.get('project', {}).get('name', ''))}</title>
<style>
body{{font:15px/1.6 system-ui,sans-serif;margin:2rem;color:#172b4d;background:#f5f7fa}}
main{{max-width:1200px;margin:auto;background:white;padding:1.5rem 2rem;border-radius:12px}}
h1{{margin-top:0}} .notice{{padding:.8rem 1rem;background:#fff4ce;border-left:4px solid #d99b00}}
.summary{{font-weight:600;margin:1.2rem 0}} table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:.65rem;border-bottom:1px solid #dfe5ec;vertical-align:top}}
th{{background:#243b53;color:white;position:sticky;top:0}} .status-passed{{color:#147d45}}
.status-failed,.status-error{{color:#b42318;font-weight:700}} .status-warning,.status-skipped{{color:#9a6700;font-weight:700}}
ul{{padding-left:1.2rem}}
</style></head><body><main>
<h1>API試験結果</h1><p>プロジェクト: {_e(master.get('project', {}).get('name', ''))}</p>
<p>生成日時: {_e(datetime.now(timezone.utc).isoformat(timespec='seconds'))}</p>
<p class="notice">仕様状態: {_e(approval_text)}。HTTP本文・認証情報はこのHTMLに保存していません。</p>
<p class="summary">{summary}</p>
<ul>{link_html}</ul>
{coverage_html}
<table><thead><tr><th>試験ID</th><th>層</th><th>試験項目</th><th>判定</th><th>レビュー状態</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</main></body></html>"""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
