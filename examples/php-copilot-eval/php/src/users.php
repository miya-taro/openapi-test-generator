<?php
require_once __DIR__ . '/db.php';

function list_users(): void
{
    $rawLimit = $_GET['limit'] ?? '20';
    $limit = filter_var($rawLimit, FILTER_VALIDATE_INT);
    if ($limit === false || $limit < 1 || $limit > 100) {
        respond_json(400, ['error' => ['code' => 'invalid_limit', 'message' => 'limit must be an integer from 1 to 100.']]);
    }

    $statement = db()->prepare('SELECT id, name, email FROM users ORDER BY id LIMIT :limit');
    $statement->bindValue(':limit', $limit, PDO::PARAM_INT);
    $statement->execute();
    $items = array_map(static function (array $row): array {
        return ['id' => (int) $row['id'], 'name' => $row['name'], 'email' => $row['email']];
    }, $statement->fetchAll(PDO::FETCH_ASSOC));

    respond_json(200, ['items' => $items, 'limit' => $limit]);
}

function get_user(string $rawId): void
{
    $id = filter_var($rawId, FILTER_VALIDATE_INT);
    if ($id === false || $id < 1) {
        respond_json(400, ['error' => ['code' => 'invalid_id', 'message' => 'id must be a positive integer.']]);
    }

    $statement = db()->prepare('SELECT id, name, email FROM users WHERE id = :id');
    $statement->execute([':id' => $id]);
    $row = $statement->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        respond_json(404, ['error' => ['code' => 'user_not_found', 'message' => 'User not found.']]);
    }

    respond_json(200, ['id' => (int) $row['id'], 'name' => $row['name'], 'email' => $row['email']]);
}

function create_user(): void
{
    $contentType = $_SERVER['CONTENT_TYPE'] ?? '';
    $mediaType = strtolower(trim(explode(';', $contentType, 2)[0]));
    if ($mediaType !== 'application/json') {
        respond_json(415, ['error' => ['code' => 'unsupported_media_type', 'message' => 'Content-Type must be application/json.']]);
    }

    $payload = json_decode(file_get_contents('php://input'));
    if (json_last_error() !== JSON_ERROR_NONE || !is_object($payload)) {
        respond_json(400, ['error' => ['code' => 'invalid_json', 'message' => 'Request body must be a JSON object.']]);
    }

    $name = isset($payload->name) && is_string($payload->name) ? trim($payload->name) : '';
    $email = isset($payload->email) && is_string($payload->email) ? $payload->email : '';
    if ($name === '' || mb_strlen($name, 'UTF-8') > 100 || mb_strlen($email, 'UTF-8') > 254 || filter_var($email, FILTER_VALIDATE_EMAIL) === false) {
        respond_json(422, ['error' => ['code' => 'validation_error', 'message' => 'name and a valid email are required.']]);
    }

    try {
        $statement = db()->prepare('INSERT INTO users (name, email) VALUES (:name, :email) RETURNING id');
        $statement->execute([':name' => $name, ':email' => $email]);
        $id = (int) $statement->fetchColumn();
    } catch (PDOException $error) {
        if ($error->getCode() === '23505') {
            respond_json(409, ['error' => ['code' => 'email_conflict', 'message' => 'Email already exists.']]);
        }
        throw $error;
    }

    respond_json(201, ['id' => $id, 'name' => $name, 'email' => $email]);
}
