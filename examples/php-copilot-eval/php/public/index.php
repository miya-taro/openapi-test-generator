<?php
require_once __DIR__ . '/../src/http.php';
require_once __DIR__ . '/../src/users.php';

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$requestUri = $_SERVER['REQUEST_URI'] ?? '/';
$path = parse_url($requestUri, PHP_URL_PATH);

if (!is_string($path)) {
    respond_json(400, ['error' => ['code' => 'bad_request', 'message' => 'Invalid request path.']]);
}

if ($path === '/api/users') {
    if ($method === 'GET') {
        list_users();
    }
    if ($method === 'POST') {
        create_user();
    }
    method_not_allowed('GET, POST');
}

if (preg_match('~^/api/users/([0-9]+)$~D', $path, $matches) === 1) {
    if ($method === 'GET') {
        get_user($matches[1]);
    }
    method_not_allowed('GET');
}

respond_json(404, ['error' => ['code' => 'not_found', 'message' => 'Route not found.']]);
