"""src/models.py は TypedDict の宣言のみで分岐ロジックを持たないが、
import時に全フィールド定義が評価されるため、import できることの確認自体が
意味のあるスモークテストになる。
"""
from src import models


def test_test_case_typed_dict_accepts_expected_fields():
    tc: models.TestCase = {
        "id": "TC-op-001",
        "operationId": "op",
        "summary": "summary",
        "path": "/users",
        "method": "GET",
        "in_": "query",
        "paramName": "page",
        "keyword": "minimum",
        "perspective": "正常系_最小値",
        "inputValue": "1",
        "expectedStatus": "200",
        "expectedResponseBody": "",
        "expectedResponseHeader": "",
        "expectedResponseTime": "3秒以内",
        "expectedResult": "正常に処理されること",
        "verdict": "",
        "notes": "",
    }
    assert tc["id"] == "TC-op-001"


def test_generate_options_typed_dict():
    opts: models.GenerateOptions = {"includeNormal": True, "includeAbnormal": True}
    assert opts["includeNormal"] is True


def test_resolved_schema_typed_dict_is_total_false():
    # total=False のため空dictでも型としては許容される
    schema: models.ResolvedSchema = {}
    schema["type"] = "string"
    schema["minLength"] = 1
    assert schema["type"] == "string"
