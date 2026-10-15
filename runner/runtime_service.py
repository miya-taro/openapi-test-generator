"""API/DB domain services. Scheduling and test lifecycle belong to pytest."""
from __future__ import annotations

import copy
import os
from contextlib import ExitStack
from datetime import datetime, timezone

import requests

from auth_login import (auth_config_for_profile, build_auth_header, load_auth_config,
                        mark_login_response_sensitive, perform_login)
from config_loader import load_config
from contract_db_guard import execute_guarded
from db_scenario_runner import _run_scenario, _safe_evidence
from execution_plan import contract_case, db_case
from http_client import execute_with_openapi
from response_schema import from_run_case
from sensitive_data import redact_header_value, redact_sensitive_text
from verifier import verify


class RuntimeService:
    def __init__(self, api, cases, options):
        self.api = copy.deepcopy(api)
        self.cases = cases
        self.options = options
        self.previous_response = {}
        self.sessions = {}
        self.headers = {}
        self.secrets = []
        self.stack = ExitStack()
        self.db_config = load_config(options["config"]) if options.get("config") else {}

    def __enter__(self):
        try:
            saved = {key: os.environ.get(key) for key in ("TEST_AUTH_HEADER_NAME", "TEST_AUTH_HEADER_VALUE")}
            def restore():
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.stack.callback(restore)
            profiles = {case["definition"].get("authProfile") for case in self.cases}
            auth = load_auth_config(self.options["auth_config"]) if self.options.get("auth_config") else None
            for profile in sorted(profiles, key=lambda value: value or ""):
                session = self.stack.enter_context(requests.Session())
                self.sessions[profile] = session
                if auth:
                    config = auth_config_for_profile(auth, profile)
                    mark_login_response_sensitive(self.api, config)
                    token = perform_login(self.options["base_url"], config, session)
                    header = build_auth_header(token, config)
                    self.secrets.extend([token, header[1]])
                    self.headers[profile] = header
                    if profile is None:
                        os.environ["TEST_AUTH_HEADER_NAME"], os.environ["TEST_AUTH_HEADER_VALUE"] = header
                    if not self.options["cookie_jar"]:
                        session.cookies.clear()
                elif profile is not None:
                    raise ValueError("認証プロファイルにはログイン設定が必要です")
            self.secrets.extend(filter(None, (os.environ.get("TEST_AUTH_HEADER_VALUE"), os.environ.get("TEST_AUTH_TOKEN"))))
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def safe(self, value):
        if isinstance(value, dict):
            return {key: self.safe(item) for key, item in _safe_evidence(value).items()}
        if isinstance(value, list):
            return [self.safe(item) for item in value]
        if isinstance(value, str):
            value = redact_sensitive_text(value)
            for secret in self.secrets:
                if secret:
                    value = value.replace(secret, "[REDACTED]")
        return value

    def run(self, case):
        record = {"caseId": case["caseId"], "kind": case["kind"],
                  "definitionHash": case["definitionHash"],
                  "executedAt": datetime.now(timezone.utc).isoformat()}
        if case["kind"] == "contract":
            current = contract_case(case)
            evidence = []
            result, failures = execute_guarded(
                current, self.api, self.db_config,
                lambda: execute_with_openapi(current, self.options["base_url"], self.api,
                                             self.sessions[None], self.options["cookie_jar"]), evidence,
            )
            verdict, detail = verify(result, from_run_case(current, self.api))
            if failures:
                verdict, detail = "NG", "; ".join(filter(None, [detail, *failures]))
            status = "error" if result.error else {"OK": "passed", "NG": "failed"}.get(verdict, "unverified")
            record.update(status=status, verdict=verdict, detail=detail, actualStatus=result.actual_status,
                          body=result.report_body if result.report_body is not None else redact_sensitive_text(result.actual_body),
                          headers={k: redact_header_value(k, v) for k, v in result.actual_headers.items()},
                          elapsedMs=result.elapsed_ms, request=result.request_evidence,
                          curl=result.curl_command, error=result.error, dbEvidence=evidence)
        else:
            scenario = db_case(case)
            evidence = {"case_id": scenario.case_id, "name": scenario.name, "executed_at": record["executedAt"]}
            ok, detail, actual, previous, cleanup_errors = _run_scenario(
                scenario, self.api, self.options["base_url"], self.db_config, self.previous_response,
                self.sessions[scenario.auth_profile], self.options["cookie_jar"],
                self.headers.get(scenario.auth_profile), evidence=evidence,
            )
            self.previous_response = previous
            status = "passed" if ok else "unverified" if detail.startswith("[UNVERIFIED]") else "failed"
            if cleanup_errors:
                status = "error"
                detail = "; ".join([detail, "後片付けに失敗しました", *cleanup_errors])
            verdict = {"passed": "OK", "unverified": "未確認"}.get(status, "NG")
            evidence.update(verdict=verdict, api_status=actual, detail=detail)
            record.update(status=status, verdict=verdict, detail=detail, actualStatus=actual,
                          evidence=evidence, cleanupErrors=cleanup_errors)
        return self.safe(record)
