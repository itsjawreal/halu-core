"""Guards against pathologically deep/large JSON payloads (Phase 8 §7).

A deeply nested `dict`/`list` is a classic low-cost DoS vector against
recursive JSON handling (ours included, e.g. `redact()` and
`stable_hash()`) -- reject it before it reaches any of that, rather
than trying to make every recursive function stack-safe individually.
"""

from __future__ import annotations

from typing import Any


def json_depth(value: Any, *, _current: int = 0) -> int:
    """The maximum nesting depth of `value`. A bare scalar is depth 0."""
    if isinstance(value, dict):
        if not value:
            return _current
        return max(json_depth(v, _current=_current + 1) for v in value.values())
    if isinstance(value, list):
        if not value:
            return _current
        return max(json_depth(v, _current=_current + 1) for v in value)
    return _current


def exceeds_max_depth(value: Any, max_depth: int) -> bool:
    return json_depth(value) > max_depth
