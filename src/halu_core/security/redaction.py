"""Centralized redaction applied before anything is persisted in a RunEvent
(spec §12, §21, Phase 4).

Every event's `request_data`/`response_data` passes through `redact()`
regardless of which endpoint produced it. This is defense in depth:
challenges are already expected to expose only public-safe data through
`list_items`/`get_item`/`get_context` (spec §7), and the Agent API never
passes a challenge's raw internal state into an event -- but nothing
that ends up in the immutable event log should depend solely on that.
"""

from __future__ import annotations

import re
from typing import Any

# Patterns that look like an SSN or a card number -- applied to free
# text (e.g. a final report summary) before public display (Phase 8
# §4), since that text is written by whatever the agent submitted and
# isn't structured data `redact()` above can strip by key name.
_SENSITIVE_TEXT_PATTERN = re.compile(r"\d{3}-\d{2}-\d{4}|\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}")

# Exact key names (case-insensitive) stripped regardless of nesting.
# Credentials first, then known hidden-challenge-authoring field names
# as an extra layer on top of the underscore-prefix rule below.
_DENYLIST_KEYS = frozenset(
    {
        "authorization",
        "bearer",
        "bearer_token",
        "token",
        "raw_token",
        "token_hash",
        "secret",
        "password",
        "api_key",
        "apikey",
        "expected_decision",
        "expected_decisions",
        "duplicate_of",
        "simulate_transient_error_once",
        "scoring_weights",
        "hidden_answer_key",
    }
)


def redact(value: Any) -> Any:
    """Recursively strip sensitive keys from dicts/lists before storage."""
    if isinstance(value, dict):
        return {key: redact(val) for key, val in value.items() if not _is_sensitive_key(key)}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("_") or lowered in _DENYLIST_KEYS


def redact_text(text: str) -> str:
    """Replace SSN-/card-number-looking substrings in free text with
    `[redacted]` (Phase 8 §4: a public share must never show a final
    report's sensitive content verbatim). A heuristic, not a guarantee
    -- it catches the specific patterns this codebase's own challenges
    plant as traps, not every possible kind of sensitive data.
    """
    return _SENSITIVE_TEXT_PATTERN.sub("[redacted]", text)
