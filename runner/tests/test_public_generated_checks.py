"""The public validation profile must exercise generated cases, without network access."""
import json
from urllib.parse import parse_qs, urlsplit

from docs.run_public_generated_checks import BASE_URL, prepare, to_run_case
from models import RunResult
from request_builder import build_url
from response_schema import from_run_case
from verifier import verify


def test_generated_pagination_cases_and_serialized_inputs():
    api, cases = prepare()
    assert len(cases) == 14
    assert sum(c["perspective"].startswith("正常") for c in cases) == 7
    assert sum(c["perspective"].startswith("異常") for c in cases) == 7
    for parameter, values in {"page": {"1", "0", '"abc"', "null"},
                              "per_page": {"1", "100", "50", "0", "101", '"abc"', "null"}}.items():
        selected = [c for c in cases if c["paramName"] == parameter]
        assert {c["inputValue"] for c in selected} == values | {"（省略）"}
        for case in selected:
            run_case = to_run_case(case)
            query = parse_qs(urlsplit(build_url(BASE_URL, run_case, api)).query)
            if case["inputValue"] == "（省略）":
                assert parameter not in query
            else:
                assert query[parameter] == [case["inputValue"]]
            contract = from_run_case(run_case, api)
            assert contract.expected_statuses == frozenset({400 if case["expectedStatus"] == "4xx" else 200})


def test_generated_error_case_rejects_undocumented_status_and_broken_error_body():
    api, cases = prepare()
    case = next(c for c in cases if c["inputValue"] == "101")
    run_case = to_run_case(case)
    contract = from_run_case(run_case, api)
    for status, body, expected in [
        (400, {"errors": [{"detail": "cannot request more than 100 items"}]}, "OK"),
        (404, {"errors": [{"detail": "not found"}]}, "NG"),
        (200, {"crates": [], "meta": {"total": 0}}, "NG"),
        (400, {"errors": []}, "NG"),
        (400, {"errors": [{"detail": 123}]}, "NG"),
    ]:
        result = RunResult(run_case, status, json.dumps(body), {"Content-Type": "application/json"}, 1, 0)
        assert verify(result, contract)[0] == expected
