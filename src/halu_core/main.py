"""Standalone entry point for self-hosting the bare core engine API.

`uvicorn halu_core.main:app` runs the Run/Token API and /health with no
branding or website. The official site (halu-web) builds its own app via
`halu_core.app.create_app()` instead of importing this module.
"""

from __future__ import annotations

from halu_core.app import create_app

app = create_app()
