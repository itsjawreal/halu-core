"""A package that only depends on halu-core must be able to register a
custom challenge into the registry without modifying any halu-core code.
This simulates that by defining a challenge locally, as an external
package (e.g. halu-web) would.
"""

from __future__ import annotations

from typing import Any

import pytest

from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult
from halu_core.challenges.registry import (
    ChallengeAlreadyRegisteredError,
    ChallengeNotFoundError,
    ChallengeRegistry,
)


class _ExternalChallenge(Challenge):
    """Stand-in for a challenge defined by a downstream package."""

    @property
    def id(self) -> str:
        return "external_test_001"

    @property
    def name(self) -> str:
        return "External Test Challenge"

    @property
    def time_limit_seconds(self) -> int:
        return 60

    @property
    def public_instructions(self) -> str:
        return "Do the one thing."

    @property
    def allowed_actions(self) -> tuple[str, ...]:
        return ("complete_run",)

    def build_initial_state(self) -> dict[str, Any]:
        return {"done": False}

    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        return ActionResult(success=True, state_changed=False)

    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        return state

    def is_complete(self, state: dict[str, Any]) -> bool:
        return bool(state.get("done"))


@pytest.fixture()
def fresh_registry() -> ChallengeRegistry:
    """An isolated registry so this test doesn't touch the global singleton."""
    return ChallengeRegistry()


def test_external_challenge_registers_without_touching_core(
    fresh_registry: ChallengeRegistry,
) -> None:
    challenge = _ExternalChallenge()
    fresh_registry.register(challenge)

    assert fresh_registry.is_registered("external_test_001")
    assert fresh_registry.get("external_test_001") is challenge
    assert challenge in fresh_registry.all()


def test_duplicate_registration_is_rejected(fresh_registry: ChallengeRegistry) -> None:
    fresh_registry.register(_ExternalChallenge())
    with pytest.raises(ChallengeAlreadyRegisteredError):
        fresh_registry.register(_ExternalChallenge())


def test_duplicate_registration_allowed_with_replace(fresh_registry: ChallengeRegistry) -> None:
    fresh_registry.register(_ExternalChallenge())
    replacement = _ExternalChallenge()
    fresh_registry.register(replacement, replace=True)
    assert fresh_registry.get("external_test_001") is replacement


def test_unknown_challenge_raises_not_found(fresh_registry: ChallengeRegistry) -> None:
    with pytest.raises(ChallengeNotFoundError):
        fresh_registry.get("does_not_exist")


def test_unregister_removes_challenge(fresh_registry: ChallengeRegistry) -> None:
    fresh_registry.register(_ExternalChallenge())
    fresh_registry.unregister("external_test_001")
    assert not fresh_registry.is_registered("external_test_001")


def test_global_registry_has_core_examples_registered_on_import() -> None:
    from halu_core.challenges.registry import registry

    assert registry.is_registered("example_ping_001")
    assert registry.is_registered("example_counter_001")


class _ExternalChallengeV2(_ExternalChallenge):
    """A newer version of `_ExternalChallenge`, same id, different version."""

    @property
    def version(self) -> str:
        return "2.0.0"


def test_two_versions_of_the_same_challenge_id_coexist(
    fresh_registry: ChallengeRegistry,
) -> None:
    v1 = _ExternalChallenge()
    v2 = _ExternalChallengeV2()
    fresh_registry.register(v1)
    fresh_registry.register(v2)

    assert fresh_registry.is_registered("external_test_001", version="1.0.0")
    assert fresh_registry.is_registered("external_test_001", version="2.0.0")
    assert fresh_registry.get("external_test_001", version="1.0.0") is v1
    assert fresh_registry.get("external_test_001", version="2.0.0") is v2


def test_registering_a_newer_version_does_not_replace_the_older_one(
    fresh_registry: ChallengeRegistry,
) -> None:
    v1 = _ExternalChallenge()
    v2 = _ExternalChallengeV2()
    fresh_registry.register(v1)
    fresh_registry.register(v2)

    # A run pinned to the old version keeps resolving the old instance
    # even after a newer version has been registered.
    assert fresh_registry.get("external_test_001", version="1.0.0") is v1


def test_lookup_without_version_resolves_the_latest_registered_version(
    fresh_registry: ChallengeRegistry,
) -> None:
    v1 = _ExternalChallenge()
    v2 = _ExternalChallengeV2()
    fresh_registry.register(v1)
    fresh_registry.register(v2)

    assert fresh_registry.get("external_test_001") is v2


def test_lookup_of_unregistered_version_is_rejected(
    fresh_registry: ChallengeRegistry,
) -> None:
    fresh_registry.register(_ExternalChallenge())
    with pytest.raises(ChallengeNotFoundError):
        fresh_registry.get("external_test_001", version="9.9.9")


def test_registering_same_id_and_version_twice_without_replace_is_rejected(
    fresh_registry: ChallengeRegistry,
) -> None:
    fresh_registry.register(_ExternalChallenge())
    with pytest.raises(ChallengeAlreadyRegisteredError):
        fresh_registry.register(_ExternalChallenge())
    # A different version of the same id is fine without replace=True.
    fresh_registry.register(_ExternalChallengeV2())
