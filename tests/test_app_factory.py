"""Tests for the create_app() runs-router extension point (Phase 8.7 §1).

These prove that:
  (a) default behavior (no args) is unchanged -- the built-in runs
      router is included exactly as before;
  (b) `include_runs_router=False` genuinely omits it -- no
      `POST /api/v1/runs` route ends up reachable on the app at all;
  (c) a caller can inject a custom router via `runs_router=` and *that*
      is the one actually mounted, with zero mutation of the shared
      `halu_core.api.runs.router` object -- this is what makes the
      extension point safe to use instead of the old router-surgery
      hack (filtering `.routes` on the shared module-level object).

Route presence/absence is verified purely through HTTP behavior via
TestClient rather than by inspecting `app.routes` structure directly --
this FastAPI version wraps `include_router()` targets in an internal
`_IncludedRouter` node rather than flattening routes onto `app.routes`,
so introspecting route objects directly is not a stable way to check
this; asking the actual ASGI app whether a route is reachable is.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from halu_core.api.runs import router as core_runs_router
from halu_core.app import create_app

_VALID_RUN_PAYLOAD = {"challenge_id": "bounty_triage_001", "agent_type": "generic"}


def test_default_create_app_includes_builtin_runs_router() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=_VALID_RUN_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    # halu-core's own bare CreateRunResponse shape.
    assert set(body.keys()) == {"run_id", "prompt", "token", "view_token", "expires_at"}


def test_include_runs_router_false_omits_it_entirely() -> None:
    app = create_app(include_runs_router=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json=_VALID_RUN_PAYLOAD)
        # No route at all handles POST /api/v1/runs anymore -- a 404,
        # not a validation error or a 405 (which would mean *some*
        # route still matched the path).
        assert response.status_code == 404
        # The rest of the API is untouched: /health and the agent
        # router are still there.
        assert client.get("/health").status_code == 200


def test_custom_runs_router_is_mounted_without_mutating_the_shared_router() -> None:
    # Snapshot the shared, module-level router object *before* anything
    # in this test touches create_app(), so we can prove afterwards it
    # was never mutated -- the exact property the old router-surgery
    # hack violated.
    original_route_count = len(core_runs_router.routes)
    original_route_paths = [getattr(r, "path", None) for r in core_runs_router.routes]

    custom_router = APIRouter(prefix="/api/v1/runs", tags=["runs"])
    marker = {"called": False}

    @custom_router.post("")
    def _custom_create_run() -> dict:  # type: ignore[no-untyped-def]
        marker["called"] = True
        return {"custom": True}

    app = create_app(include_runs_router=True, runs_router=custom_router)

    with TestClient(app) as client:
        response = client.post("/api/v1/runs", json={})
        assert response.status_code == 200
        assert response.json() == {"custom": True}
        assert marker["called"] is True

    # And -- the whole point -- the shared, module-level router object
    # halu_core.api.runs.router was never mutated by any of this.
    assert len(core_runs_router.routes) == original_route_count
    assert [getattr(r, "path", None) for r in core_runs_router.routes] == original_route_paths
