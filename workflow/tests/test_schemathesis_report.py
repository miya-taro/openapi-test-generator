from workflow.schemathesis_report import write_exploratory_html


def test_html_report_escapes_junit_controlled_text_and_counts_results(tmp_path):
    junit = tmp_path / "junit.xml"
    output = tmp_path / "report.html"
    junit.write_text(
        """<testsuites tests="2" failures="1" errors="0" skipped="0">
        <testsuite name="suite &lt;script&gt;">
          <testcase name="GET /users &lt;img src=x&gt;" time="0.1" />
          <testcase name="GET /private">
            <failure message="broken &lt;script&gt;">response &lt;b&gt;body&lt;/b&gt;</failure>
          </testcase>
        </testsuite>
        </testsuites>""",
        encoding="utf-8",
    )

    write_exploratory_html(junit, output, title="探索 & <結果>")
    rendered = output.read_text(encoding="utf-8")

    assert "探索 &amp; &lt;結果&gt;" in rendered
    assert "GET /users &lt;img src=x&gt;" in rendered
    assert "broken &lt;script&gt;" in rendered
    assert "response &lt;b&gt;body&lt;/b&gt;" in rendered
    assert "<script>" not in rendered
    assert "2" in rendered


def test_html_report_rejects_malformed_junit_with_clear_error(tmp_path):
    junit = tmp_path / "bad.xml"
    junit.write_text("<testsuites>", encoding="utf-8")

    try:
        write_exploratory_html(junit, tmp_path / "report.html", title="探索")
    except ValueError as exc:
        assert "JUnit" in str(exc)
    else:
        raise AssertionError("malformed JUnit should be rejected")
