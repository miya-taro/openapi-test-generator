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

_NEXT_ACTIONS = {
    'passed': '設定した照合に合格。未設定の条件まで保証するものではありません。',
    'failed': '結果Excelの判定理由で期待値と実測値を比較してください。',
    'error': '通信・接続設定と実行ログを確認してください。',
    'warning': '結果Excelの警告理由と応答時間を確認してください。',
    'skipped': '判定できていません。試験データ・対応範囲を確認してください。',
    'not-run': '今回の実行記録がありません。対象選択・承認・中断の有無を確認してください。',
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
                status = "not-run" if testcase.get("classname") == "not-run" else "skipped"
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
            if testcase.get("classname") == "execution":
                continue  # Run-level setup/teardown errors are not runnable case IDs.
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
    case_ids = {case["caseId"] for case in cases}
    execution_errors = [key for key, status in statuses.items() if key not in case_ids and status == "error"]
    execution_notice = (
        '<p class="notice status-error">実行全体のエラーがあります。準備・後片付けなどを完了できていません。'
        '結果Excelの「実行エラー」またはJUnitを確認してください。</p>'
    ) if execution_errors else ""
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
    priority = {'failed': 0, 'error': 0, 'warning': 1, 'skipped': 1, 'not-run': 2, 'passed': 3}
    for case, status in sorted(zip(cases, run_statuses, strict=True), key=lambda item: priority[item[1]]):
        kind = "API契約" if case.get("kind") == "contract" else "DB照合"
        review = case.get("reviewStatus", "draft")
        review_label = {'draft': '下書き', 'reviewed': 'レビュー済み', 'approved': '承認済み'}.get(review, '未確認')
        expected = case.get('expected', {})
        expected_status = expected.get('status') if case.get('kind') == 'contract' else (expected.get('response') or {}).get('status')
        source = case.get('source', {})
        api = source.get('operationId', '')
        rows.append(
            f'<tr data-status="{_e(status)}" data-review="{_e(review)}">'
            f"<td><strong>{_e(case.get('title'))}</strong><small>{_e(case.get('caseId'))} ・ {_e(review_label)}</small></td>"
            f"<td>{_e(api)}<small>{_e(kind)}</small></td>"
            f"<td class=\"status-{_e(status)}\">{_e(_STATUS_LABELS[status])}</td>"
            f"<td>{_e(expected_status if expected_status is not None else '記録なし')}</td>"
            f"<td>{_e(_NEXT_ACTIONS[status])}</td>"
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
    attention = any(status != 'passed' for status in run_statuses)

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
ul{{padding-left:1.2rem}} small{{display:block;color:#53657a;font-size:12px;overflow-wrap:anywhere}}
.result-toolbar{{display:flex;gap:20px;flex-wrap:wrap;align-items:center;margin:20px 0 8px}}
.result-toolbar input[type=search]{{padding:10px;border:1px solid #9aaac0;border-radius:6px;width:260px;max-width:100%}}
.table-wrap{{overflow:auto}} #results td{{min-width:90px;overflow-wrap:anywhere}} #results td:first-child{{min-width:240px}}
#results th{{white-space:nowrap}} #results tr[data-status=failed],#results tr[data-status=error]{{background:#fff4f2}}
[hidden]{{display:none!important}} @media(max-width:700px){{body{{margin:0}}main{{padding:16px}}}}
@media(max-width:700px){{
  #results thead{{display:none}} #results tbody{{display:block}}
  #results tr{{display:grid;grid-template-columns:1fr 1fr;border:1px solid #dfe5ec;border-radius:8px;margin:12px 0}}
  #results td,#results td:first-child{{min-width:0}}
  #results td:first-child,#results td:last-child{{grid-column:1 / -1}}
  #results td:nth-child(3)::before{{content:'判定：'}}
  #results td:nth-child(4){{grid-column:1 / -1}}
  #results td:nth-child(4)::before{{content:'期待ステータス：'}}
}}
</style></head><body><main>
<h1>API試験結果</h1><p>プロジェクト: {_e(master.get('project', {}).get('name', ''))}</p>
<p>生成日時: <time id="generated-at" datetime="{_e(datetime.now(timezone.utc).isoformat(timespec='seconds'))}">{_e(datetime.now(timezone.utc).strftime('%Y/%m/%d %H:%M UTC'))}</time></p>
<p class="notice">仕様状態: {_e(approval_text)}。HTTP本文・認証情報はこのHTMLに保存していません。</p>
<p class="summary">{summary}</p>
{execution_notice}
<ul>{link_html}</ul>
{coverage_html}
<div class="result-toolbar">
<label><input id="attention-only" type="checkbox" {'checked' if attention else ''}> 要確認のみ（NG・エラー・警告・未確認・未実行）</label>
<label>試験項目・APIを検索 <input id="result-search" type="search" placeholder="試験名・API名・試験ID"></label>
</div><p id="visible-count" aria-live="polite"></p>
<div class="table-wrap"><table id="results"><thead><tr><th>試験項目</th><th>API / 試験の種類</th><th>判定</th><th>期待ステータス</th><th>次に確認すること</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</div>
<script>
const rows = [...document.querySelectorAll('#results tbody tr')];
const generatedAt = document.getElementById('generated-at');
generatedAt.textContent = new Date(generatedAt.dateTime).toLocaleString('ja-JP', {{timeZoneName:'short'}});
function filterResults() {{
  const query = document.getElementById('result-search').value.trim().toLocaleLowerCase();
  const only = document.getElementById('attention-only').checked;
  let count = 0;
  for (const row of rows) {{
    row.hidden = (only && row.dataset.status === 'passed') || !row.textContent.toLocaleLowerCase().includes(query);
    if (!row.hidden) count++;
  }}
  document.getElementById('visible-count').textContent = `${{count}} / ${{rows.length}}件を表示` + (count ? '' : '（該当なし。絞り込み条件を変更してください）');
}}
document.getElementById('attention-only').addEventListener('change', filterResults);
document.getElementById('result-search').addEventListener('input', filterResults);
filterResults();
</script>
</main></body></html>"""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
