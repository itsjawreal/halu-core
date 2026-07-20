"""A catch-all handler that guarantees no unhandled exception ever
reaches a client as a raw traceback (Phase 6.5 §9).

FastAPI/Starlette's own `HTTPException` handling is untouched -- it
already returns `{"detail": ...}` exactly as every existing endpoint
and test expects. This module only adds a fallback for exceptions
*nothing* else caught: log the full traceback server-side (with the
request id for correlation) and return a generic, safe JSON body.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from halu_core.logging_config import error_logger
from halu_core.observability import get_request_id


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = get_request_id(request.scope)
        error_logger.exception(
            "Unhandled exception", extra={"request_id": request_id}, exc_info=exc
        )
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "internal_error",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
            },
        )
