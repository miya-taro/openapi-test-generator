import json
import shlex
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from http_client import execute_with_openapi
from models import RunCase
from request_evidence import readable_curl
from response_schema import from_run_case
from src.extractor import extract_specs
from src.generator import generate_test_cases
from src.renderer.readable_spec import simple_request


def test_generated_header_probes_reach_server_with_valid_body():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.headers.get('Content-Type'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(400)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    api = {'paths': {'/login': {'post': {'operationId': 'login',
        'requestBody': {'required': True, 'content': {'application/json': {'schema': {
            'type': 'object', 'required': ['user'], 'properties': {'user': {'type': 'string', 'example': 'test'}}}}}},
        'responses': {'200': {'description': 'OK'}, '400': {'description': 'Bad request'}}}}}}
    p, b = extract_specs(api)
    cases = generate_test_cases(p, b, {'includeNormal': True, 'includeAbnormal': True, 'enumFullCoverage': True, 'oneOfFullCoverage': True})
    probes = [c for c in cases if c['paramName'] == 'Content-Type']
    assert len(probes) == 2
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with requests.Session() as session:
            session.headers['Content-Type'] = 'application/json'
            for tc in probes:
                case = RunCase('header', 'login', '/login', 'POST', 'header', 'Content-Type', tc['inputValue'], tc['expectedStatus'], '', '', '', '')
                result = execute_with_openapi(case, f'http://127.0.0.1:{server.server_port}', api, session)
                expected_header = None if tc['inputValue'] == '（省略）' else tc['inputValue']
                assert received[-1] == (expected_header, {'user': 'test'})
                assert result.actual_status == 400
                assert from_run_case(case, api).expected_statuses == frozenset({400})
                if shutil.which('curl'):
                    _, command = simple_request(readable_curl(result.request_evidence))
                    replay = subprocess.run(shlex.split(command), capture_output=True, timeout=10)
                    assert replay.returncode == 0
                    assert received[-1] == (expected_header, {'user': 'test'})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
