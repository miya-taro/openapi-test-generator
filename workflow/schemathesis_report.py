from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from pathlib import Path


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def write_exploratory_html(junit_path: str | Path, output_path: str | Path, *, title: str) -> None:
    source = Path(junit_path)
    try:
        root = ET.parse(source).getroot()
    except (ET.ParseError, OSError) as exc:
        raise ValueError(f"SchemathesisのJUnit XMLを読み込めません: {source}: {exc}") from exc

    rows: list[str] = []
    counts = {"成功": 0, "失敗": 0, "エラー": 0, "スキップ": 0}
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        detail = failure if failure is not None else error
        if failure is not None:
            status = "失敗"
            explanation = failure.get("message") or ""
        elif error is not None:
            status = "エラー"
            explanation = error.get("message") or ""
        elif skipped is not None:
            status = "スキップ"
            explanation = skipped.get("message") or ""
        else:
            status = "成功"
            explanation = ""
        if detail is not None and detail.text:
            explanation = f"{explanation}\n{detail.text}".strip()
        counts[status] += 1
        rows.append(
            "<tr>"
            f"<td>{_e(status)}</td><td>{_e(case.get('name'))}</td>"
            f"<td>{_e(case.get('classname'))}</td><td>{_e(case.get('time'))}</td>"
            f"<td><pre>{_e(explanation)}</pre></td></tr>"
        )

    summary = "　".join(f"{_e(name)} {count}" for name, count in counts.items())
    document = f"""<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#172033}}h1{{font-size:1.5rem}}
.summary{{padding:1rem;background:#f1f5f9;border-radius:.5rem}}table{{border-collapse:collapse;width:100%;margin-top:1rem}}
th,td{{padding:.65rem;border:1px solid #d5dce5;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap;max-width:55rem;margin:0}}
</style>
<body><h1>{_e(title)}</h1><p class="summary">{summary}</p>
<p>応答本文を含む場合があります。ローカルの試験証跡として取り扱ってください。</p>
<table><thead><tr><th>判定</th><th>試験</th><th>操作</th><th>秒</th><th>詳細</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>
"""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
