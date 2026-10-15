"""Regex dependency replacement retains valid, reproducible contract inputs."""
import random
import re

import pytest
from src.pattern_samples import pattern_samples
from src.schema_example import find_schema_example


@pytest.mark.parametrize('pattern', [r'^[A-Z]{2}-[0-9]{4}$', r'^(red|green|blue)$',
    r'^(ab)\1$', r'^[-a-z0-9_]{3,12}$', r'^日本[0-9]{2}$', r'^\d{128}$'])
def test_candidates_are_reproducible_valid_and_do_not_change_global_random(pattern):
    state = random.getstate()
    first = list(pattern_samples(pattern, 20))
    assert first and all(re.search(pattern, value) for value in first)
    assert first == list(pattern_samples(pattern, 20))
    assert random.getstate() == state
    value = find_schema_example({'type': 'string', 'pattern': pattern})
    assert re.search(pattern, value)


def test_unsupported_and_excessive_patterns_do_not_produce_false_normal_cases():
    for pattern in ['[invalid', r'^(a{4096}){4096}$', r'^a{4096}b{4096}$', r'^a{999999999}$', r'^(?!a)a$']:
        assert not list(pattern_samples(pattern, 5))
