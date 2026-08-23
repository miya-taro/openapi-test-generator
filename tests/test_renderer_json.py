import json
import re

from src.renderer.json_output import build_output, write_output

CASES = [
    {"perspective": "正常系_省略", "id": "TC-op-001"},
    {"perspective": "正常系_enum代表値", "id": "TC-op-002"},
    {"perspective": "異常系_必須欠落", "id": "TC-op-003"},
]

_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_build_output_counts_normal_and_abnormal():
    output = build_output(CASES, "openapi.json")
    assert output["meta"]["totalCases"] == 3
    assert output["meta"]["normalCases"] == 2
    assert output["meta"]["abnormalCases"] == 1
    assert output["meta"]["source"] == "openapi.json"
    assert output["cases"] == CASES


def test_build_output_generated_at_is_iso8601_utc_z():
    output = build_output(CASES, "openapi.json")
    assert _ISO_Z.match(output["meta"]["generatedAt"])


def test_build_output_empty_cases():
    output = build_output([], "openapi.json")
    assert output["meta"]["totalCases"] == 0
    assert output["meta"]["normalCases"] == 0
    assert output["meta"]["abnormalCases"] == 0


def test_write_output_writes_readable_utf8_json(tmp_path):
    output = build_output(CASES, "openapi.json")
    out_path = tmp_path / "out.json"
    write_output(output, str(out_path))

    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded == output


def test_write_output_preserves_non_ascii_characters(tmp_path):
    cases = [{"perspective": "正常系_省略", "summary": "日本語のサマリー"}]
    output = build_output(cases, "openapi.json")
    out_path = tmp_path / "out.json"
    write_output(output, str(out_path))

    raw = out_path.read_text(encoding="utf-8")
    assert "日本語のサマリー" in raw  # ensure_ascii=False で \uXXXX にエスケープされていない
