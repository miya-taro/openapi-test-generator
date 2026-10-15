"""Qualification of the new runtime with real HTTP, login and PostgreSQL."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "runner"), str(ROOT)]
from workflow.case_master import build_case_master, write_case_master


@pytest.mark.skipif(not os.environ.get("OTG_INTEGRATION_DB_CONFIG"), reason="requires dedicated PostgreSQL")
@pytest.mark.parametrize("kind", ["plan-post", "plan-get", "pwrco"])
def test_normal_and_faulty_apis_through_pytest_and_login(tmp_path, kind):
    from docs.authenticated_fixture import AuthenticatedFixture
    from docs.login_fixture_api import LoginFixture, TOKEN, PASSWORD
    from docs.plan_fixture_api import PlanFixture
    from docs.plan_get_fixture_api import PlanGetFixture
    from docs.pwrco_fixture_api import PwrcoFixture
    from docs.plan_test_suites import post_suite, get_suite
    from docs.pwrco_suite import build_suite

    config = json.loads(os.environ["OTG_INTEGRATION_DB_CONFIG"])
    cls, spec_file, fault = {
        "plan-post": (PlanFixture, "examples/plan-post-openapi.json", "numeric"),
        "plan-get": (PlanGetFixture, "examples/plan-get/openapi.json", "value"),
        "pwrco": (PwrcoFixture, "examples/pwrco/openapi.json", "rate"),
    }[kind]
    fixture, login, gateway = cls(config), LoginFixture(), None
    try:
        suite = (post_suite(fixture.table, fixture.site_table) if kind == "plan-post" else
                 get_suite(fixture.definition()) if kind == "plan-get" else
                 build_suite("2039-01-01T00:00:00+09:00", fixture.table, fixture.site_table))
        api = json.loads((ROOT / spec_file).read_text(encoding="utf-8"))
        route = next(iter(api["paths"]))
        gateway = AuthenticatedFixture(login.url, fixture.url, route)
        scenarios = tmp_path / "scenarios.json"
        cfg = tmp_path / "db.json"
        cfg.write_text(json.dumps({"postgres": config}), encoding="utf-8")
        auth = ROOT / "examples/login/auth.json"
        for mode in ("normal", "fault"):
            current = suite
            if mode == "fault":
                fixture.fault = fault
                current = {"scenarios": [suite["scenarios"][0]]}
                if kind == "pwrco":
                    current = {"scenarios": [build_suite("2040-01-01T00:00:00+09:00", fixture.table, fixture.site_table)["scenarios"][0]]}
            scenarios.write_text(json.dumps(current), encoding="utf-8")
            master = build_case_master("qualification", None, scenarios, ROOT / spec_file)
            path = tmp_path / "case-master.json"
            write_case_master(master, path)
            before = len(gateway.calls)
            result = subprocess.run([
                sys.executable, str(ROOT / "runner/pytest_runner.py"), str(path), "--kind", "db-scenario",
                "--base-url", gateway.url, "--config", str(cfg), "--auth-config", str(auth), "--skip-health-check",
                "--output", str(tmp_path / f"{mode}.xlsx"), "--junit-xml", str(tmp_path / f"{mode}.xml"),
            ], capture_output=True, text=True, encoding="utf-8", timeout=120)
            assert result.returncode == (0 if mode == "normal" else 1), result.stdout + result.stderr
            payload = (tmp_path / f"{mode}.json").read_text(encoding="utf-8")
            assert TOKEN not in payload and PASSWORD not in payload
            rows = json.loads(payload)["cases"]
            assert len(rows) == len(current["scenarios"])
            assert all(row["status"] == ("passed" if mode == "normal" else "failed") for row in rows)
            calls = gateway.calls[before:]
            assert calls[0]["login"] is True
            assert all(call["authenticated"] for call in calls[1:])
    finally:
        if gateway:
            gateway.close()
        login.close()
        fixture.close()
