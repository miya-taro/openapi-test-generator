export const FORMAT_VALID_SAMPLES: Record<string, string> = {
  'date': '2024-01-01',
  'date-time': '2024-01-01T00:00:00Z',
  'time': '12:00:00',
  'email': 'test@example.com',
  'uri': 'https://example.com',
  'uuid': '550e8400-e29b-41d4-a716-446655440000',
  'ipv4': '192.168.0.1',
  'ipv6': '::1',
  'byte': 'SGVsbG8=',
  'password': 'P@ssw0rd',
}

export const FORMAT_INVALID_SAMPLES: Record<string, string> = {
  'date': 'not-a-date',
  'date-time': '2024-01-01 00:00:00',
  'time': '25:00:00',
  'email': 'not-an-email',
  'uri': 'not a uri',
  'uuid': 'not-a-uuid',
  'ipv4': '999.999.999.999',
  'ipv6': 'not-ipv6',
  'byte': 'not==base64!',
  'password': null as unknown as string,
}
