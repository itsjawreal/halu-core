"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request
from sqlmodel import Session

from halu_core.config import settings
from halu_core.db import get_session as _get_session
from halu_core.models.enums import EventType, TokenScope
from halu_core.models.run import Run
from halu_core.services import event_service
from halu_core.services.rate_limit_service import RateLimitConfig
from halu_core.services.run_service import (
    InvalidTokenError,
    RunNotActiveError,
    RunNotFoundError,
    authenticate,
)
from halu_core.timeutils import utc_now


def get_session() -> Generator[Session, None, None]:
    yield from _get_session()


def get_current_time() -> datetime:
    """The clock the Agent API rate limiter uses.

    Overridden in tests (the same way `get_session` is) to drive rate
    limiting with a fake, controllable clock instead of real sleeps.
    """
    return utc_now()


def get_rate_limit_config() -> RateLimitConfig:
    """Read/write rate limits for the Agent API (spec §21).

    Overridden in tests to use small limits so a test can trip the
    limiter in a handful of requests instead of dozens.
    """
    return RateLimitConfig(
        read_limit=settings.rate_limit_read_per_minute,
        write_limit=settings.rate_limit_write_per_minute,
        window_seconds=settings.rate_limit_window_seconds,
    )


def _parse_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def require_scope(scope: TokenScope) -> Callable[..., Run]:
    """Build a dependency that authenticates a run and enforces `scope`.

    Every Agent API endpoint (spec §10.2-§10.6) depends on one of
    these: it enforces that the token belongs to this run, is not
    missing, malformed, expired, disabled, or otherwise invalid, that
    the run can still accept requests (not completed or expired), and
    -- ahead of any of that being challenge-specific -- that the token
    actually carries the scope this endpoint requires (spec §11, §21).
    Scope is compared as an exact value from `token.scope`, never as a
    substring match.

    Every rejection here is logged as a `request_rejected` event
    (spec §12), except when there is no run to attach it to at all
    (a missing token, or a run_id that doesn't exist) -- those two
    cases are the "invalid bearer token that cannot be linked to a
    specific run" the spec exempts from event logging.
    """

    def _dependency(
        request: Request,
        run_id: str,
        authorization: str | None = Header(default=None),
        session: Session = Depends(get_session),
    ) -> Run:
        raw_token = _parse_bearer_token(authorization)
        if raw_token is None:
            raise HTTPException(
                status_code=401,
                detail={"error_code": "missing_token", "message": "A bearer token is required."},
            )

        try:
            run, token = authenticate(session, run_id, raw_token)
        except RunNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail={"error_code": "run_not_found", "message": str(exc)}
            ) from exc
        except InvalidTokenError as exc:
            event_service.record_event(
                session,
                run_id=run_id,
                event_type=EventType.REQUEST_REJECTED,
                source="agent_api",
                method=request.method,
                endpoint=request.url.path,
                status_code=401,
                success=False,
                state_changed=False,
                error_code="invalid_token",
                response_data={"message": str(exc)},
            )
            raise HTTPException(
                status_code=401, detail={"error_code": "invalid_token", "message": str(exc)}
            ) from exc
        except RunNotActiveError as exc:
            event_service.record_event(
                session,
                run_id=run_id,
                event_type=EventType.REQUEST_REJECTED,
                source="agent_api",
                method=request.method,
                endpoint=request.url.path,
                status_code=409,
                success=False,
                state_changed=False,
                error_code="run_not_active",
                response_data={"message": str(exc)},
            )
            raise HTTPException(
                status_code=409, detail={"error_code": "run_not_active", "message": str(exc)}
            ) from exc

        if scope.value not in token.scope:
            event_service.record_event(
                session,
                run_id=run_id,
                event_type=EventType.REQUEST_REJECTED,
                source="agent_api",
                method=request.method,
                endpoint=request.url.path,
                status_code=403,
                success=False,
                state_changed=False,
                error_code="insufficient_scope",
                response_data={"required_scope": scope.value},
            )
            raise HTTPException(
                status_code=403,
                detail={
                    "error_code": "insufficient_scope",
                    "message": f"This token does not carry the {scope.value!r} scope.",
                },
            )

        return run

    return _dependency


require_challenge_read = require_scope(TokenScope.CHALLENGE_READ)
require_items_read = require_scope(TokenScope.ITEMS_READ)
require_actions_write = require_scope(TokenScope.ACTIONS_WRITE)
require_run_complete = require_scope(TokenScope.RUN_COMPLETE)
require_events_read = require_scope(TokenScope.EVENTS_READ)
