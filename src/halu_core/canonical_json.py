"""Canonical, deterministic JSON used anywhere two independent
serializations of the same data must hash identically -- idempotency
request hashing (spec §10.5) and event state hashing (spec §12, Phase 4).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_dumps(data: Any) -> str:
    return json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))


def canonical_hash(data: Any) -> str:
    return hashlib.sha256(canonical_dumps(data).encode("utf-8")).hexdigest()
