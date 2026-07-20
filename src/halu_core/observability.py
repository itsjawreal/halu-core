"""Request correlation and structured access logging (Phase 6.5 §9).

Every request gets a `request_id` (surfaced back to the client as an
`X-Request-ID` response header, and attached to the access log line and
any error logged for that request), so a single log line or a support
report can be traced to the exact request that produced it.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from halu_core.logging_config import access_logger

_REQUEST_ID_HEADER = b"x-request-id"


def get_request_id(scope: Scope) -> str:
    request_id = scope.get("request_id")
    return str(request_id) if request_id else "unknown"


class RequestIDMiddleware:
    """Assigns a request id, logs one structured access line per request,
    and echoes the id back as `X-Request-ID`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        scope["request_id"] = request_id
        start = time.monotonic()
        status: dict[str, Any] = {"code": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode()))
                message = {**message, "headers": headers}
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            access_logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status["code"],
                    "duration_ms": round(duration_ms, 2),
                },
            )
