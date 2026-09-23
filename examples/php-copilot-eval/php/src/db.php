<?php
function db(): PDO
{
    $dsn = getenv('APP_DSN');
    if ($dsn === false || $dsn === '') {
        throw new RuntimeException('APP_DSN is not configured.');
    }

    $user = getenv('APP_DB_USER');
    $password = getenv('APP_DB_PASSWORD');

    return new PDO(
        $dsn,
        $user === false ? '' : $user,
        $password === false ? '' : $password,
        [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]
    );
}
