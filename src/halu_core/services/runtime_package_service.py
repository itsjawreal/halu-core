"""Registration and lookup for immutable full-agent runtime packages."""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from halu_core.models.enums import ReproducibilityTier
from halu_core.models.runtime_package import RuntimePackage


class RuntimePackageConflictError(Exception):
    """The same name/version/config digest is already registered."""


def create_runtime_package(
    session: Session,
    *,
    name: str,
    version: str,
    reproducibility: ReproducibilityTier,
    config_digest: str,
    artifact_digest: str | None = None,
    soul_digest: str | None = None,
    memory_config_digest: str | None = None,
    toolset_digest: str | None = None,
    orchestration_digest: str | None = None,
    recovery_digest: str | None = None,
    framework_name: str | None = None,
    framework_version: str | None = None,
    declared_models: list[dict[str, Any]] | None = None,
    public_metadata: dict[str, Any] | None = None,
) -> RuntimePackage:
    existing = session.exec(
        select(RuntimePackage).where(
            RuntimePackage.name == name,
            RuntimePackage.version == version,
            RuntimePackage.config_digest == config_digest,
        )
    ).first()
    if existing is not None:
        return existing

    package = RuntimePackage(
        name=name,
        version=version,
        reproducibility=reproducibility,
        config_digest=config_digest,
        artifact_digest=artifact_digest,
        soul_digest=soul_digest,
        memory_config_digest=memory_config_digest,
        toolset_digest=toolset_digest,
        orchestration_digest=orchestration_digest,
        recovery_digest=recovery_digest,
        framework_name=framework_name,
        framework_version=framework_version,
        declared_models=declared_models or [],
        public_metadata=public_metadata or {},
    )
    session.add(package)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise RuntimePackageConflictError(
            "This runtime package version and config digest already exist."
        ) from exc
    session.refresh(package)
    return package


def get_runtime_package(session: Session, runtime_package_id: str) -> RuntimePackage | None:
    return session.get(RuntimePackage, runtime_package_id)
