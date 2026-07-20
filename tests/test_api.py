"""Tests for the FastAPI HTTP layer."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bare_engine_has_no_branded_web_routes(client: TestClient) -> None:
    # halu-core intentionally ships no website; that's halu-web's job.
    response = client.get("/")
    assert response.status_code == 404


def test_create_run_returns_prompt_and_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs", json={"challenge_id": "bounty_triage_001", "agent_type": "openclaw"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"].startswith("run_")
    assert "Bearer " + body["token"] in body["prompt"]


def test_get_run_returns_summary_without_token(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/runs", json={"challenge_id": "bounty_triage_001", "agent_type": "generic"}
    )
    run_id = create_response.json()["run_id"]

    response = client.get(f"/api/v1/runs/{run_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == "active"
    assert "token" not in body


def test_get_run_404_for_unknown_run(client: TestClient) -> None:
    response = client.get("/api/v1/runs/run_does_not_exist")
    assert response.status_code == 404


def test_create_run_rejects_invalid_agent_type(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs", json={"challenge_id": "bounty_triage_001", "agent_type": "not-a-real-agent"}
    )
    assert response.status_code == 422
