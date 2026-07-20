"""Shared time helper.

SQLite (used for the MVP) does not preserve timezone offsets on stored
datetimes -- values round-trip back as naive. To keep every in-process and
round-tripped datetime directly comparable, the whole codebase standardizes
on naive datetimes that are always UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current UTC time as a naive datetime (no tzinfo)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
