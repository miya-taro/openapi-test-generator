"""Local-only login fixture. Status codes are assumptions, not user API requirements."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERNAME = 'fixture-user'
PASSWORD = 'fixture-password-only'
TOKEN = 'fixture-session-id-only'


class LoginFixture(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(('127.0.0.1', 0), Handler)
        self.fault = None
        self.calls = []
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}'

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=5)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, status, body):
        encoded = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        if self.path != '/v1/auth/login':
            return self.respond(404, {'error': 'not found'})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        except ValueError:
            body = None
        self.server.calls.append({'path': self.path, 'body': body})
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return self.respond(400, {'error': 'invalid content type'})
        valid_shape = isinstance(body, dict) and all(isinstance(body.get(key), str) for key in ('username', 'password'))
        if not valid_shape and self.server.fault != 'accept-invalid':
            return self.respond(400, {'error': 'invalid input'})
        if valid_shape and (body['username'] != USERNAME or body['password'] != PASSWORD) and self.server.fault != 'accept-password':
            return self.respond(401, {'error': 'authentication failed'})
        response = {'id': TOKEN, 'created_datetime': '2026-10-12T12:00:00+09:00'}
        if self.server.fault == 'missing-id':
            del response['id']
        if self.server.fault == 'wrong-id-type':
            response['id'] = 123
        if self.server.fault == 'missing-date':
            del response['created_datetime']
        if self.server.fault == 'invalid-date':
            response['created_datetime'] = 'not-a-date'
        return self.respond(200, response)

    def do_GET(self):
        if self.path != '/v1/protected':
            return self.respond(404, {'error': 'not found'})
        authenticated = self.headers.get('auth-key') == TOKEN
        self.server.calls.append({'path': self.path, 'authenticated': authenticated})
        if not authenticated and self.server.fault != 'ignore-auth':
            return self.respond(401, {'error': 'authentication failed'})
        return self.respond(200, {'ok': True})
