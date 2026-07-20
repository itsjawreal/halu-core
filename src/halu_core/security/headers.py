"""Security response headers (Phase 6.5 §4).

Defaults are sane for a bare JSON API (no frames, no third-party
resources, no legacy MIME sniffing). A caller building a browser-facing
site on top (e.g. halu-web) passes its own `csp`/`permissions_policy`
to `create_app()` to relax only what its own pages actually need --
the bare engine's own routes (health, runs, agent API) never do.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
DEFAULT_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), interest-cohort=()"


class SecurityHeadersMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        csp: str = DEFAULT_CSP,
        permissions_policy: str = DEFAULT_PERMISSIONS_POLICY,
    ) -> None:
        self.app = app
        self._extra_headers = [
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", permissions_policy.encode()),
            (b"x-frame-options", b"DENY"),
            (b"content-security-policy", csp.encode()),
        ]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._extra_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
