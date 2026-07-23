"""The Alembic revision this codebase expects a persistent database to
be at. Kept as a plain constant (rather than shelling out to Alembic at
request time) so the readiness check stays cheap and dependency-free.

Bump this whenever a new migration is added under `alembic/versions/`.
"""

from __future__ import annotations

EXPECTED_MIGRATION_HEAD = "0008"
