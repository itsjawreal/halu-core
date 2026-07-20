"""FastAPI application factory for the HALU Checker engine.

This module intentionally does not mount any branded website: the home
page, official templates, and branding live in halu-web, which imports
`create_app()` from here and layers its own routers on top. Running this
module directly gives a bare, self-hostable Run + Token API with no
branding -- useful for anyone self-hosting just the open-source engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import halu_core.challenges  # noqa: F401  (registers example challenges on import)
from halu_core import __version__
from halu_core.api.agent import router as agent_router
from halu_core.api.runs import router as _default_runs_router
from halu_core.challenges.quality import validate_all_registered
from halu_core.challenges.registry import registry
from halu_core.db import ensure_database_ready
from halu_core.errors import register_error_handlers
from halu_core.logging_config import configure_logging
from halu_core.observability import RequestIDMiddleware
from halu_core.readiness import run_readiness_checks
from halu_core.security.headers import (
    DEFAULT_CSP,
    DEFAULT_PERMISSIONS_POLICY,
    SecurityHeadersMiddleware,
)
from halu_core.security.request_limits import MaxBodySizeMiddleware

DEFAULT_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB: comfortably above any legit request today


class HealthResponse(BaseModel):
    status: str
    version: str


class StartupValidationError(RuntimeError):
    """A registered challenge failed startup manifest validation."""


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ensure_database_ready()
    # Startup validation (Phase 8 §1): every registered challenge must
    # have a buildable, non-empty benchmark manifest, in every
    # environment -- a challenge whose manifest hooks are broken is
    # always a bug, not just a production concern.
    problems = validate_all_registered(registry.all())
    if problems:
        raise StartupValidationError(
            "One or more registered challenges failed manifest validation:\n  - "
            + "\n  - ".join(problems)
        )
    yield


def create_app(
    *,
    title: str = "HALU Checker Core",
    description: str = "Verify what your AI agent actually did.",
    csp: str = DEFAULT_CSP,
    permissions_policy: str = DEFAULT_PERMISSIONS_POLICY,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    readiness_challenge_ids: tuple[str, ...] = (),
    include_runs_router: bool = True,
    runs_router: APIRouter | None = None,
) -> FastAPI:
    """Build a FastAPI app exposing the core Run/Token API and /health.

    Callers (e.g. halu-web) may call `app.include_router(...)` on the
    returned instance to layer additional routers on top, and pass
    their own `csp`/`permissions_policy` if their pages need looser
    defaults than a bare JSON API does (e.g. to load their own
    same-origin static assets).

    Extension point (added in 0.9.0) for callers that need a different
    `POST /api/v1/runs` (e.g. one that returns a richer response body
    than halu-core's own bare `CreateRunResponse`): pass
    ``include_runs_router=False`` to omit halu-core's built-in runs
    router entirely, and/or pass ``runs_router=<your APIRouter>`` to
    have *that* router included instead. This lets a downstream app
    swap in its own implementation without ever mutating
    `halu_core.api.runs.router` (a shared, module-level object) in
    place -- the previous workaround for this was exactly that kind of
    mutation, which is fragile (it corrupts the object for every other
    importer in the same process, including tests) and no longer
    necessary.

    Passing no arguments preserves the exact previous behavior: the
    default `runs_router` (halu-core's own) is included whenever
    `include_runs_router` is left at its default of `True`.
    """
    configure_logging()

    app = FastAPI(title=title, description=description, version=__version__, lifespan=_lifespan)
    effective_runs_router = runs_router if runs_router is not None else _default_runs_router
    if include_runs_router:
        app.include_router(effective_runs_router)
    app.include_router(agent_router)

    register_error_handlers(app)

    # Middleware order matters: Starlette applies them innermost-added
    # first, so adding request-id last makes it the outermost wrapper,
    # guaranteeing every response (including one from the size-limit or
    # security-headers layers) still gets an X-Request-ID and an access
    # log line.
    app.add_middleware(MaxBodySizeMiddleware, max_body_bytes=max_body_bytes)
    app.add_middleware(
        SecurityHeadersMiddleware, csp=csp, permissions_policy=permissions_policy
    )
    app.add_middleware(RequestIDMiddleware)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Liveness check (kept for backward compatibility)."""
        return HealthResponse(status="ok", version=__version__)

    @app.get("/health/live", response_model=HealthResponse)
    def health_live() -> HealthResponse:
        """Liveness: is the process up at all? Never touches the database."""
        return HealthResponse(status="ok", version=__version__)

    @app.get("/health/ready")
    def health_ready() -> JSONResponse:
        """Readiness: can this instance actually serve traffic?

        Checks database connectivity, that a persistent database is at
        the migration head this code expects, and that every challenge
        id this deployment is supposed to serve is actually registered.
        Returns 503 (not 200) when not ready, so a load balancer or
        orchestrator can route around this instance.
        """
        ok, checks = run_readiness_checks(readiness_challenge_ids)
        body = {"status": "ok" if ok else "not_ready", "checks": [c.to_dict() for c in checks]}
        return JSONResponse(status_code=200 if ok else 503, content=body)

    return app
