FORMAT_VALID_SAMPLES: dict[str, str] = {
    "date": "2024-01-01",
    "date-time": "2024-01-01T00:00:00Z",
    "time": "12:00:00",
    "email": "test@example.com",
    "uri": "https://example.com",
    "uuid": "550e8400-e29b-41d4-a716-446655440000",
    "ipv4": "192.168.0.1",
    "ipv6": "::1",
    "byte": "SGVsbG8=",
    "password": "P@ssw0rd",
}

FORMAT_INVALID_SAMPLES: dict[str, str] = {
    "date": "not-a-date",
    "date-time": "2024-01-01 00:00:00",
    "time": "25:00:00",
    "email": "not-an-email",
    "uri": "not a uri",
    "uuid": "not-a-uuid",
    "ipv4": "999.999.999.999",
    "ipv6": "not-ipv6",
    "byte": "not==base64!",
    # password: 異常サンプルなし（TS版も null 相当。format のみでは異常系を生成しない）
}
