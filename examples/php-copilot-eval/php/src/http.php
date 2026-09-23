<?php
function respond_json(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($body, JSON_UNESCAPED_UNICODE);
    exit;
}

function method_not_allowed(string $allowedMethods): void
{
    header('Allow: ' . $allowedMethods);
    respond_json(405, ['error' => ['code' => 'method_not_allowed', 'message' => 'Method not allowed.']]);
}
