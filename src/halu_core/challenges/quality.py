"""Automated challenge quality checks (Phase 7.5).

Run once at registration time (see `ChallengeRegistry.register`) so a
broken or incomplete challenge is caught immediately -- loudly, at
import/startup time -- rather than silently corrupting scores or
leaking hidden data through some code path discovered later.

Two properties are *not* checked here, deliberately: "every expected
action is reachable" and "no impossible objective" require semantic
understanding of a challenge's own hidden rules that no generic,
static check can verify (core has no idea what a "correct" decision
looks like for any given challenge). Those are validated empirically
instead, by each official challenge's own test suite driving a full
run through its hidden answer key.
"""

from __future__ import annotations

from typing import Any

from halu_core.challenges.base import Challenge


class ChallengeQualityError(Exception):
    """A challenge failed one or more automated quality checks."""


def _leaks_hidden_key(value: Any) -> bool:
    """Whether `value` contains any dict key starting with `_` -- this
    codebase's convention for "server-only bookkeeping, never public".
    """
    if isinstance(value, dict):
        return any(
            (isinstance(key, str) and key.startswith("_")) or _leaks_hidden_key(sub)
            for key, sub in value.items()
        )
    if isinstance(value, list):
        return any(_leaks_hidden_key(item) for item in value)
    return False


def validate_challenge(challenge: Challenge) -> list[str]:
    """Return a list of human-readable violations; empty means it passes."""
    violations: list[str] = []

    if not challenge.id:
        violations.append("id must be a non-empty string")
    if not challenge.name:
        violations.append("name must be non-empty")
    if not challenge.category:
        violations.append("category must be non-empty")
    if not challenge.difficulty:
        violations.append("difficulty must be non-empty")
    if not challenge.description:
        violations.append("description must be non-empty")
    if not challenge.public_instructions:
        violations.append("public_instructions must be non-empty")
    if challenge.estimated_duration_minutes <= 0:
        violations.append("estimated_duration_minutes must be positive")
    if not challenge.allowed_actions:
        violations.append("allowed_actions must be non-empty")

    weights = challenge.scoring_weight_overrides()
    if weights is not None:
        total = sum(weights.values())
        if abs(total - 1.0) > 1e-6:
            violations.append(f"scoring_weight_overrides() must sum to 1.0, got {total}")

    try:
        state_a = challenge.build_initial_state()
        state_b = challenge.build_initial_state()
    except Exception as exc:  # noqa: BLE001 - report, don't crash the caller
        violations.append(f"build_initial_state() raised: {exc}")
        state_a = None
    else:
        if state_a != state_b:
            violations.append("build_initial_state() is not deterministic across calls")

    if state_a is not None:
        for item in challenge.list_items(state_a):
            if _leaks_hidden_key(item):
                violations.append("list_items() leaks a hidden ('_'-prefixed) key")
                break
        if _leaks_hidden_key(challenge.get_context(state_a)):
            violations.append("get_context() leaks a hidden ('_'-prefixed) key")
        if not challenge.list_objectives(state_a):
            violations.append("list_objectives() must return at least one objective")

    try:
        hash_a = challenge.dataset_hash()
        hash_b = challenge.dataset_hash()
    except Exception as exc:  # noqa: BLE001
        violations.append(f"dataset_hash() raised: {exc}")
    else:
        if hash_a != hash_b:
            violations.append("dataset_hash() is not stable across calls for the same version")

    try:
        manifest = challenge.manifest()
    except Exception as exc:  # noqa: BLE001
        violations.append(f"manifest() raised: {exc}")
    else:
        has_all_hashes = (
            manifest.dataset_hash and manifest.hidden_truth_hash and manifest.scoring_rules_hash
        )
        if not has_all_hashes:
            violations.append("manifest() produced an empty hash")

    return violations


def validate_all_registered(challenges: list[Challenge]) -> list[str]:
    """Startup check (spec Phase 8 §1): every already-registered challenge
    must have a buildable, non-empty manifest. Returns a list of
    per-challenge violation summaries; empty means everything passes.

    Deliberately re-validates challenges that are already in the
    registry (skipping the registry's own at-registration check would
    miss a challenge whose manifest hooks broke due to a later code
    change, e.g. a shared module-level constant becoming unhashable).
    """
    problems: list[str] = []
    for challenge in challenges:
        violations = validate_challenge(challenge)
        if violations:
            problems.append(
                f"{challenge.id!r} version {challenge.version!r}: {'; '.join(violations)}"
            )
    return problems
