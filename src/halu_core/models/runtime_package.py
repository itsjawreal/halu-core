"""Immutable identity for one complete agent-runtime configuration."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from halu_core.models.enums import ReproducibilityTier
from halu_core.timeutils import utc_now


def _new_runtime_package_id() -> str:
    return f"rtpkg_{uuid.uuid4().hex[:12]}"


class RuntimePackage(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "name", "version", "config_digest", name="uq_runtime_package_version_config"
        ),
    )

    id: str = Field(default_factory=_new_runtime_package_id, primary_key=True)
    name: str = Field(index=True)
    version: str
    reproducibility: ReproducibilityTier
    config_digest: str
    artifact_digest: str | None = None
    soul_digest: str | None = None
    memory_config_digest: str | None = None
    toolset_digest: str | None = None
    orchestration_digest: str | None = None
    recovery_digest: str | None = None
    framework_name: str | None = None
    framework_version: str | None = None
    declared_models: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    public_metadata: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utc_now)
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
