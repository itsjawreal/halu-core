"""Reject oversized request bodies before a route ever sees them
(Phase 6.5 §3, spec §21's "request body size limit").

Checks `Content-Length` up front when present (the common case for
JSON/form POSTs); a request that omits or lies about its length and
streams more than `max_body_bytes` anyway is caught while its body is
drained, too.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _PayloadTooLarge(Exception):
    pass


class MaxBodySizeMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_body_bytes:
                    await _reject_too_large(send)
                    return
            except ValueError:
                pass

        total = 0

        async def receive_wrapper() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b"") or b"")
                if total > self.max_body_bytes:
                    raise _PayloadTooLarge()
            return message

        try:
            await self.app(scope, receive_wrapper, send)
        except _PayloadTooLarge:
            await _reject_too_large(send)


async def _reject_too_large(send: Send) -> None:
    body = b'{"error_code":"payload_too_large","message":"Request body too large."}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
