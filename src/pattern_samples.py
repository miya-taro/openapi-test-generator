"""Deterministic regex candidates using the BSD-3-Clause rstr library.

Candidates are validated before use; unsupported patterns produce no candidate,
not a guessed successful request. No global random state is changed.
"""
from random import Random
import re

try:
    from rstr import Rstr
except ImportError:  # optional fallback for incomplete runtime installations
    Rstr = None


class _MinimumRepeats(Random):
    def randint(self, a, b):
        return a


class _BoundedRstr(Rstr if Rstr is not None else object):
    def xeger(self, pattern):
        self._steps = 20000
        result = super().xeger(pattern)
        if len(result) > 4096:
            raise ValueError("pattern candidate too long")
        return result

    def _handle_state(self, state):
        self._steps -= 1
        if self._steps < 0:
            raise ValueError("pattern candidate budget exceeded")
        result = super()._handle_state(state)
        if len(result) > 4096:
            raise ValueError("pattern candidate too long")
        return result

    def _handle_repeat(self, minimum, maximum, value):
        # rstr caps repeats at 100, even when a schema requires a longer fixed code.
        if minimum > 4096:
            raise ValueError("pattern repetition too large")
        count = self._random.randint(minimum, max(minimum, min(maximum, 100)))
        return ''.join(self._build_string(value) for _ in range(count))


def pattern_samples(pattern: str, limit: int = 100):
    if Rstr is None:
        return
    try:
        compiled = re.compile(pattern)
        # Try the shortest repeats first, then a reproducible sequence of alternatives.
        generators = [_BoundedRstr(_MinimumRepeats(0)), _BoundedRstr(Random(0))]
        seen = set()
        for index in range(limit):
            candidate = generators[min(index, 1)].xeger(pattern)
            if candidate not in seen and compiled.search(candidate):
                seen.add(candidate)
                yield candidate
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError, re.error):
        return
