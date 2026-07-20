"""Tests for Phase 6.5 §4/§9: security headers, request-id, request size
limits, production config validation, and the unhandled-exception
fallback that never leaks a traceback.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from halu_core.config import ConfigError, Settings, _validate


def test_health_response_has_security_headers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in response.headers
    assert "permissions-policy" in response.headers


def test_response_has_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 32  # uuid4 hex


def test_each_request_gets_a_different_request_id(client: TestClient) -> None:
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first != second


def test_oversized_request_body_is_rejected(client: TestClient) -> None:
    huge_payload = {"challenge_id": "x" * (2 * 1024 * 1024), "agent_type": "generic"}
    response = client.post("/api/v1/runs", json=huge_payload)
    assert response.status_code == 413
    assert response.json()["error_code"] == "payload_too_large"


def _settings(**overrides: object) -> Settings:
    base = dict(
        env="production",
        data_dir="./data",
        database_url="postgresql://user:pass@host/db",
        base_url="https://halu.example.com",
        default_run_ttl_seconds=1800,
        token_byte_length=32,
        rate_limit_read_per_minute=120,
        rate_limit_write_per_minute=60,
        rate_limit_window_seconds=60,
        view_token_ttl_seconds=604800,
        max_run_ttl_seconds=86400,
        max_actions_per_run=500,
        max_final_report_length=20000,
        max_claims_per_report=100,
        max_json_depth=20,
        retention_incomplete_run_days=7,
        retention_completed_run_days=90,
        retention_public_share_days=365,
        retention_event_days=90,
        retention_expired_token_days=30,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_production_config_rejects_in_memory_sqlite() -> None:
    with pytest.raises(ConfigError):
        _validate(_settings(database_url="sqlite://"))


def test_production_config_rejects_localhost_base_url() -> None:
    with pytest.raises(ConfigError):
        _validate(_settings(base_url="https://127.0.0.1:8000"))


def test_production_config_rejects_non_https_base_url() -> None:
    with pytest.raises(ConfigError):
        _validate(_settings(base_url="http://halu.example.com"))


def test_production_config_rejects_short_token_length() -> None:
    with pytest.raises(ConfigError):
        _validate(_settings(token_byte_length=8))


def test_production_config_accepts_a_sane_configuration() -> None:
    _validate(_settings())  # must not raise


def test_development_config_is_not_validated_strictly() -> None:
    dev_settings = _settings(
        env="development",
        database_url="sqlite://",
        base_url="http://127.0.0.1:8000",
        token_byte_length=8,
    )
    _validate(dev_settings)  # must not raise -- dev has no such restrictions


def test_unhandled_exception_never_leaks_a_traceback(client: TestClient) -> None:
    # example_ping_001's own state row is untouched; force an internal
    # error downstream of routing by hitting a route with a run_id that
    # cannot possibly resolve to valid SQL parameters gracefully handled
    # elsewhere -- instead, directly assert the documented contract of
    # the catch-all handler using a monkeypatched route would require
    # app internals, so here we assert the shape any 500 must have by
    # checking the handler's response contract directly.
    from starlette.testclient import TestClient as StarletteTestClient

    from halu_core.app import create_app

    app = create_app()

    @app.get("/__boom")
    def boom() -> None:
        raise RuntimeError("kaboom - this must never reach the client")

    with StarletteTestClient(app, raise_server_exceptions=False) as boom_client:
        response = boom_client.get("/__boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "kaboom" not in response.text
    assert "Traceback" not in response.text
    assert "request_id" in body
