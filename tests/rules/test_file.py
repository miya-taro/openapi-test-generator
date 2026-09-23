from src.generator.rules.file import generate_file_cases, FILE_UPLOAD_MARKER

ALL_OPTS = {"includeNormal": True, "includeAbnormal": True, "enumFullCoverage": False}
NORMAL_ONLY = {"includeNormal": True, "includeAbnormal": False, "enumFullCoverage": False}
ABNORMAL_ONLY = {"includeNormal": False, "includeAbnormal": True, "enumFullCoverage": False}


def _ctx(opts) -> dict:
    return {"paramIn": "body", "paramName": "avatar", "opts": opts, "successStatus": "201"}


def test_generates_normal_upload_case():
    cases = generate_file_cases(_ctx(ALL_OPTS))
    assert len(cases) == 1
    assert cases[0]["perspective"] == "正常系_ファイルアップロード"
    assert cases[0]["inputValue"] == FILE_UPLOAD_MARKER
    assert cases[0]["expectedStatus"] == "201"


def test_no_case_when_include_normal_false():
    cases = generate_file_cases(_ctx(ABNORMAL_ONLY))
    assert cases == []


def test_case_generated_with_normal_only_opts():
    cases = generate_file_cases(_ctx(NORMAL_ONLY))
    assert len(cases) == 1
