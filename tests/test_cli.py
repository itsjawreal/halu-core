"""Tests for the Typer CLI."""

from __future__ import annotations

import os

os.environ.setdefault("HALU_CORE_DATABASE_URL", "sqlite://")

from typer.testing import CliRunner  # noqa: E402

from halu_core import __version__  # noqa: E402
from halu_core.cli import app  # noqa: E402

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_create_run_command_prints_prompt_and_run_id() -> None:
    result = runner.invoke(
        app, ["create-run", "--challenge-id", "bounty_triage_001", "--agent-type", "hermes"]
    )
    assert result.exit_code == 0
    assert "run_id:" in result.stdout
    assert "Bearer" in result.stdout


def test_create_run_command_rejects_bad_agent_type() -> None:
    result = runner.invoke(
        app, ["create-run", "--challenge-id", "bounty_triage_001", "--agent-type", "not-real"]
    )
    assert result.exit_code != 0
