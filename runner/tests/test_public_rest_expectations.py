"""Offline regressions for public REST checks; no requests to public services."""
import json

import pytest

from docs.run_public_rest_checks import FIXTURE, profiles, response_controls, to_run_case
from src.parser import parse_openapi
from models import RunResult
from response_schema import from_run_case
from verifier import verify


@pytest.mark.parametrize("name,count", [("readPost", 1), ("filterPosts", 9), ("patchPost", 1)])
def test_public_response_contract_detects_incorrect_data(tmp_path, name, count):
    specs, groups = profiles()
    path = tmp_path / "openapi.json"
    path.write_text(json.dumps(specs["jsonplaceholder"]), encoding="utf-8")
    api = parse_openapi(str(path))
    case = next(c for c in groups["jsonplaceholder"] if c["summary"] == name)
    posts = json.loads(FIXTURE.read_text(encoding="utf-8"))["posts"]
    body = posts if name == "filterPosts" else posts[0]
    if name == "patchPost":
        body = {**body, "title": "otg-patched"}
    result = RunResult(to_run_case(case), 200, json.dumps(body),
                       {"Content-Type": "application/json"}, 1, 0)
    assert verify(result, from_run_case(result.case, api))[0] == "OK"
    controls = response_controls(result, case, api)
    assert len(controls) == count
    assert all(c["verdict"] == c["expected"] for c in controls), controls
    if name == "filterPosts":
        assert {c["mutation"] for c in controls if c["verdict"] == "NG"} == {
            "empty", "missing_row", "duplicate_row", "extra_row", "wrong_id",
            "wrong_owner", "wrong_content", "duplicate_id_different_content",
        }
        assert next(c for c in controls if c["mutation"] == "reordered")["verdict"] == "OK"
