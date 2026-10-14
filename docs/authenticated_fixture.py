"""Local authentication layer around independent DB fixture APIs (401 is provisional)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from docs.login_fixture_api import TOKEN


class AuthenticatedFixture:
    def __init__(self, login_url, upstream_url, path):
        self.calls = []
        self.fault = None
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def handle_api(self):
                payload = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                login = self.path == '/v1/auth/login'
                authenticated = self.headers.get('auth-key') == TOKEN
                fixture.calls.append({'path': self.path, 'method': self.command,
                                      'authenticated': authenticated, 'login': login})
                if not login and self.path != path:
                    return self.respond(404, b'')
                if not login and not authenticated and fixture.fault != 'ignore-auth':
                    if fixture.fault == 'write-before-deny':
                        requests.request(self.command, upstream_url+self.path, data=payload,
                                         headers={'Content-Type':'application/json'}, timeout=10)
                    return self.respond(401, b'')
                response = requests.request(self.command, (login_url if login else upstream_url)+self.path,
                                            data=payload, headers=({'Content-Type': self.headers['Content-Type']}
                                                                   if 'Content-Type' in self.headers else {}), timeout=10)
                self.respond(response.status_code, response.content, response.headers.get('Content-Type'))

            def respond(self, status, payload, content_type=None):
                self.send_response(status)
                if content_type:
                    self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = handle_api
            do_POST = handle_api

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
