import json
from pathlib import Path

import pytest

from src import cli

FIXTURE = str(Path(__file__).resolve().parent / "e2e" / "fixtures" / "simple.openapi.json")


def run_cli(monkeypatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["cli.py", *argv])
    return cli.main()


def test_missing_input_file_returns_1(monkeypatch, tmp_path, capsys):
    code = run_cli(monkeypatch, [str(tmp_path / "does_not_exist.json")])
    assert code == 1


def test_dry_run_prints_count_and_returns_0(monkeypatch, capsys):
    code = run_cli(monkeypatch, [FIXTURE, "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "生成ケース数" in out


def test_generates_json_output(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(out_path)])
    assert code == 0
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["meta"]["totalCases"] > 0
    assert len(data["cases"]) == data["meta"]["totalCases"]


def test_fail_if_exists_returns_3_when_output_present(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    out_path.write_text("{}", encoding="utf-8")
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(out_path), "--fail-if-exists"])
    assert code == 3


def test_excel_output_option_creates_xlsx(monkeypatch, tmp_path):
    json_path = tmp_path / "cases.json"
    excel_path = tmp_path / "cases.xlsx"
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(json_path), "--excel-output", str(excel_path)])
    assert code == 0
    assert excel_path.exists()


def test_operations_filter_reduces_cases(monkeypatch, tmp_path):
    out_all = tmp_path / "all.json"
    run_cli(monkeypatch, [FIXTURE, "-o", str(out_all)])
    all_cases = json.loads(out_all.read_text(encoding="utf-8"))["cases"]

    out_filtered = tmp_path / "filtered.json"
    run_cli(monkeypatch, [FIXTURE, "-o", str(out_filtered), "--operations", "getUser"])
    filtered_cases = json.loads(out_filtered.read_text(encoding="utf-8"))["cases"]

    assert 0 < len(filtered_cases) < len(all_cases)
    assert all(c["operationId"] == "getUser" for c in filtered_cases)


def test_exclude_ops_filter_removes_operation(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(out_path), "--exclude-ops", "getUser"])
    assert code == 0
    cases = json.loads(out_path.read_text(encoding="utf-8"))["cases"]
    assert not any(c["operationId"] == "getUser" for c in cases)
    assert len(cases) > 0


def test_no_normal_flag_excludes_normal_cases(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    run_cli(monkeypatch, [FIXTURE, "-o", str(out_path), "--no-normal"])
    cases = json.loads(out_path.read_text(encoding="utf-8"))["cases"]
    assert not any(c["perspective"].startswith("正常系") for c in cases)
    assert len(cases) > 0


def test_no_abnormal_flag_excludes_abnormal_cases(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    run_cli(monkeypatch, [FIXTURE, "-o", str(out_path), "--no-abnormal"])
    cases = json.loads(out_path.read_text(encoding="utf-8"))["cases"]
    assert not any(c["perspective"].startswith("異常系") for c in cases)
    assert len(cases) > 0


def test_invalid_openapi_version_returns_1(monkeypatch, tmp_path):
    bad = tmp_path / "openapi.json"
    bad.write_text(json.dumps({"openapi": "2.0", "paths": {}}), encoding="utf-8")
    code = run_cli(monkeypatch, [str(bad), "-o", str(tmp_path / "out.json")])
    assert code == 1


def test_invalid_json_returns_1(monkeypatch, tmp_path):
    bad = tmp_path / "openapi.json"
    bad.write_text("{not valid json", encoding="utf-8")
    code = run_cli(monkeypatch, [str(bad), "-o", str(tmp_path / "out.json")])
    assert code == 1


def test_log_level_flag_does_not_crash(monkeypatch, tmp_path):
    out_path = tmp_path / "cases.json"
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(out_path), "--log-level", "debug"])
    assert code == 0


def test_unresolvable_ref_returns_2(monkeypatch, tmp_path):
    bad = tmp_path / "openapi.json"
    bad.write_text(
        json.dumps({
            "openapi": "3.1.0",
            "paths": {
                "/x": {
                    "get": {
                        "operationId": "getX",
                        "parameters": [{"name": "id", "in": "path", "schema": {"$ref": "#/components/schemas/Missing"}}],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
        }),
        encoding="utf-8",
    )
    code = run_cli(monkeypatch, [str(bad), "-o", str(tmp_path / "out.json")])
    assert code == 2


def test_unexpected_error_during_output_returns_3(monkeypatch, tmp_path):
    # 出力先の親ディレクトリが存在しない場合、JSON書き込みで例外が発生し
    # OpenAPIParseError 以外の汎用 except 節（exit 3）に落ちる
    out_path = tmp_path / "no_such_dir" / "cases.json"
    code = run_cli(monkeypatch, [FIXTURE, "-o", str(out_path)])
    assert code == 3
