"""Tests for agent prompt generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from halu_core.models.enums import AgentType
from halu_core.models.run import Run
from halu_core.services.prompt_service import generate_prompt


@pytest.fixture()
def run() -> Run:
    return Run(
        id="run_test123",
        challenge_id="bounty_triage_001",
        agent_type=AgentType.OPENCLAW,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )


def test_prompt_includes_base_url_and_run_id(run: Run) -> None:
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000")
    assert "http://127.0.0.1:8000/api/v1/runs/run_test123" in prompt


def test_prompt_includes_bearer_token(run: Run) -> None:
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000")
    assert "Bearer raw-token-value" in prompt


def test_prompt_never_mentions_a_permanent_key(run: Run) -> None:
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000")
    assert "permanent" not in prompt.lower()
    assert "api_key" not in prompt.lower()


@pytest.mark.parametrize(
    "agent_type,expected_snippet",
    [
        (AgentType.OPENCLAW, "HTTP tool access"),
        (AgentType.HERMES, "callable function"),
        (AgentType.GENERIC, "curl"),
    ],
)
def test_prompt_style_note_varies_by_agent_type(
    agent_type: AgentType, expected_snippet: str
) -> None:
    run = Run(
        id="run_test123",
        challenge_id="bounty_triage_001",
        agent_type=agent_type,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000")
    assert expected_snippet in prompt


def test_prompt_strips_trailing_slash_from_base_url(run: Run) -> None:
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000/")
    assert "8000//api" not in prompt


def test_prompt_documents_claims_format_with_task_completed_example(run: Run) -> None:
    prompt = generate_prompt(run, "raw-token-value", "http://127.0.0.1:8000")
    assert '"claims"' in prompt
    assert '{"type": "task_completed", "value": true}' in prompt
