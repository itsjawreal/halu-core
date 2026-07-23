"""Control-plane API for immutable full-agent runtime packages."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session

from halu_core.api.dependencies import get_session
from halu_core.models.enums import ReproducibilityTier
from halu_core.models.runtime_package import RuntimePackage
from halu_core.services.runtime_package_service import (
    RuntimePackageConflictError,
    create_runtime_package,
    get_runtime_package,
)

router = APIRouter(prefix="/api/v1/runtime-packages", tags=["runtime-packages"])

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class RuntimePackageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    reproducibility: ReproducibilityTier
    config_digest: str
    artifact_digest: str | None = None
    soul_digest: str | None = None
    memory_config_digest: str | None = None
    toolset_digest: str | None = None
    orchestration_digest: str | None = None
    recovery_digest: str | None = None
    framework_name: str | None = Field(default=None, max_length=200)
    framework_version: str | None = Field(default=None, max_length=100)
    declared_models: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    public_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "config_digest",
        "artifact_digest",
        "soul_digest",
        "memory_config_digest",
        "toolset_digest",
        "orchestration_digest",
        "recovery_digest",
    )
    @classmethod
    def validate_digest(cls, value: str | None) -> str | None:
        if value is not None and _DIGEST_PATTERN.fullmatch(value) is None:
            raise ValueError("digest must use sha256:<64 lowercase hex>")
        return value


class RuntimePackageView(BaseModel):
    id: str
    name: str
    version: str
    reproducibility: ReproducibilityTier
    config_digest: str
    artifact_digest: str | None
    soul_digest: str | None
    memory_config_digest: str | None
    toolset_digest: str | None
    orchestration_digest: str | None
    recovery_digest: str | None
    framework_name: str | None
    framework_version: str | None
    declared_models: list[dict[str, Any]]
    public_metadata: dict[str, Any]
    created_at: datetime


def _view(package: RuntimePackage) -> RuntimePackageView:
    return RuntimePackageView.model_validate(package, from_attributes=True)


@router.post("", response_model=RuntimePackageView, status_code=201)
def register_runtime_package(
    payload: RuntimePackageCreate, session: Session = Depends(get_session)
) -> RuntimePackageView:
    try:
        package = create_runtime_package(session, **payload.model_dump())
    except RuntimePackageConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "runtime_package_conflict", "message": str(exc)},
        ) from exc
    return _view(package)


@router.get("/{runtime_package_id}", response_model=RuntimePackageView)
def read_runtime_package(
    runtime_package_id: str, session: Session = Depends(get_session)
) -> RuntimePackageView:
    package = get_runtime_package(session, runtime_package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Runtime package not found.")
    return _view(package)
