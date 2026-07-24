"""Abstract Challenge protocol every challenge implementation conforms to.

This module defines *how* a challenge plugs into the engine: it says
nothing about what any specific challenge's state, rules, or scoring look
like. Official challenges, their initial datasets, hidden validation
rules, and expected end states live in halu-web (or any other package
that registers into `halu_core.challenges.registry`), never here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from halu_core.challenges.manifest import (
    SCORING_ENGINE_VERSION,
    ChallengeManifest,
    stable_hash,
)
from halu_core.challenges.models import ActionRequest, ActionResult, ChallengeDescriptor
from halu_core.challenges.verification import (
    ActionRecord,
    ActionVerdict,
    ClaimVerification,
    ObjectiveStatus,
    SafetyIncident,
)


class Challenge(ABC):
    """A single evaluatable task an agent can be scored against.

    Implementations are expected to be stateless singletons: all
    per-run mutable state lives in the plain `dict[str, Any]` passed to
    and returned from `build_initial_state`/`apply_action`, not on the
    Challenge instance itself, so one registered instance can safely
    back many concurrent runs.
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """Stable identifier used in the registry and in `Run.challenge_id`."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable challenge name."""

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    @abstractmethod
    def time_limit_seconds(self) -> int:
        """Maximum run duration for this challenge (spec §7)."""

    @property
    @abstractmethod
    def public_instructions(self) -> str:
        """The task description shown to the agent. Must not leak hidden rules."""

    @property
    @abstractmethod
    def allowed_actions(self) -> tuple[str, ...]:
        """The action names this challenge recognizes (spec §7)."""

    def action_schemas(self) -> dict[str, dict[str, Any]]:
        """Public example request bodies keyed by action name."""
        return {}

    # -- Descriptive metadata (Phase 7) --------------------------------
    #
    # Purely informational: shown on the challenge-selection page and in
    # `describe()`/`ChallengeDescriptor`, never consulted by validation
    # or scoring. Defaults keep pre-Phase-7 challenges (ping/counter,
    # Bounty Manager) working unchanged if they don't override these.

    @property
    def category(self) -> str:
        return "general"

    @property
    def difficulty(self) -> str:
        return "unspecified"

    @property
    def estimated_duration_minutes(self) -> int:
        return max(1, self.time_limit_seconds // 60)

    @property
    def capabilities_tested(self) -> tuple[str, ...]:
        return ()

    @property
    def description(self) -> str:
        """A short, public summary -- distinct from `public_instructions`,
        which is the full task brief served to an agent. Defaults to the
        first line of `public_instructions` (falling back to `name`) so
        this is never empty even for a challenge that doesn't override it."""
        stripped = self.public_instructions.strip()
        first_line = stripped.splitlines()[0] if stripped else ""
        return first_line or self.name

    @property
    def recommended_agent_types(self) -> tuple[str, ...]:
        return ()

    @abstractmethod
    def build_initial_state(self) -> dict[str, Any]:
        """Construct a fresh state dict for a new run of this challenge."""

    @abstractmethod
    def validate_action(self, state: dict[str, Any], action: ActionRequest) -> ActionResult:
        """Check whether `action` is well-formed and currently permitted.

        Must not mutate `state`. Correctness of the agent's *decision*
        (e.g. whether approving a given submission was the right call)
        is a scoring concern (spec §13), not a validation concern: a
        well-formed action against a valid target should validate
        successfully even if it is later scored as the wrong call.
        """

    @abstractmethod
    def apply_action(self, state: dict[str, Any], action: ActionRequest) -> dict[str, Any]:
        """Return the state resulting from applying an already-validated action.

        Implementations should treat `state` as immutable input and
        return a new dict rather than mutating it in place. If `action`
        would not pass `validate_action`, implementations must return
        `state` unchanged.
        """

    @abstractmethod
    def is_complete(self, state: dict[str, Any]) -> bool:
        """Whether this run's objectives have all been addressed."""

    def list_items(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Public-safe summaries of this run's items (spec §10.3).

        Not every challenge is item-based (e.g. the ping/counter
        examples), so the default is an empty list. Item-based
        challenges (e.g. Bounty Manager) override this and must strip
        any hidden/answer-key fields before returning.
        """
        return []

    def get_item(self, state: dict[str, Any], item_id: str) -> dict[str, Any] | None:
        """Public-safe detail for one item, or None if it doesn't exist (spec §10.4)."""
        return None

    def get_context(self, state: dict[str, Any]) -> dict[str, Any]:
        """Public-safe supplementary context for this run (spec §10.2).

        For challenges whose items must be judged against some public
        rubric (e.g. Bounty Manager's per-bounty requirements), this is
        where that rubric is served -- so an agent can compare raw item
        data against stated requirements itself, rather than reading a
        pre-computed verdict off the item. Core has no opinion on what
        "context" contains; the default is empty for challenges (like
        the ping/counter examples) that don't need any.
        """
        return {}

    def get_episode_profile_context(self, profile: str) -> dict[str, Any]:
        """Public benchmark-owned context for one full-agent profile.

        Challenge packages may expose signed memory fixtures, adversarial
        notices, virtual-time gates, or delegation constraints. The default
        is intentionally empty so existing challenges remain compatible.
        Hidden truth must never be returned here.
        """
        return {}

    def is_flaky_item(self, state: dict[str, Any], item_id: str) -> bool:
        """Whether this item should simulate one transient read error.

        This is a pure predicate over already-built state -- it must
        not mutate anything or track whether the error has already
        fired. The Agent API layer owns that one-time bookkeeping
        (spec §12's "Temporary API error" trap; see
        `halu_core.services.flaky_service`), precisely so this trap
        never has to live inside a challenge's state-mutation logic.
        """
        return False

    def list_objectives(self, state: dict[str, Any]) -> list[ObjectiveStatus]:
        """The objectives task_completion is scored against (spec §13.1).

        Default: a single objective mirroring `is_complete`. A
        challenge with several independent objectives (e.g. one per
        item that needs triage) should override this so partial
        progress is reflected proportionally rather than all-or-nothing.
        """
        return [
            ObjectiveStatus(
                id="complete",
                description="Run objectives are complete.",
                completed=self.is_complete(state),
            )
        ]

    def compute_metrics(self, state: dict[str, Any]) -> dict[str, Any]:
        """Actual, verifiable metrics derived from final state (spec §13.3).

        Default: none. A challenge exposes whatever facts its claim
        types need to be checked against (e.g. counts, booleans).
        """
        return {}

    def verify_claim(
        self,
        claim_type: str,
        claimed_value: Any,
        *,
        state: dict[str, Any],
        metrics: dict[str, Any],
    ) -> ClaimVerification | None:
        """Check one claim against this challenge's ground truth (spec §13.3).

        Return None if `claim_type` isn't recognized -- the scoring
        engine then records it as UNVERIFIED itself. Only a challenge
        that recognizes a claim type may return NOT_APPLICABLE (for a
        genuinely subjective/non-verifiable claim); core never assigns
        that status on its own.
        """
        return None

    def evaluate_action(self, action: ActionRecord, state: dict[str, Any]) -> ActionVerdict:
        """Whether one executed action was the objectively correct call (spec §13.2).

        Default: NOT_APPLICABLE (this challenge has no notion of a
        "correct" decision per target, e.g. the ping/counter examples).
        """
        return ActionVerdict.NOT_APPLICABLE

    def safety_incidents(
        self, state: dict[str, Any], actions: list[ActionRecord]
    ) -> list[SafetyIncident]:
        """Hidden safety violations detected in the final state (spec §13.8).

        Default: none. A challenge with a prompt-injection trap (or any
        other trap whose compliance is only visible in the final state)
        reports it here.
        """
        return []

    def expected_minimum_calls(self, state: dict[str, Any]) -> int:
        """A rough lower bound on meaningful API calls needed to finish (spec §13.7).

        Used only for the efficiency score. Default: 1.
        """
        return 1

    def scoring_weight_overrides(self) -> dict[str, float] | None:
        """Override the HALU Score's component weights (spec §14).

        Return None to use the engine's default weights.
        """
        return None

    # -- Benchmark manifest (Phase 7.5) ---------------------------------
    #
    # Only hashes/version/timestamps are ever exposed publicly -- never
    # the dataset or hidden-truth content those hashes are computed from.

    @property
    def published_at(self) -> str:
        """A fixed ISO timestamp for when this challenge *version* was
        published. Must be a stable constant a challenge author sets
        per version, never `datetime.now()` -- otherwise the manifest
        hash and this field would differ across processes/runs, breaking
        reproducibility. Override per version when publishing a new one.
        """
        return "2026-01-01T00:00:00Z"

    def dataset_hash(self) -> str:
        """Hash of this version's initial dataset.

        Default: hash of `build_initial_state()`. That includes any
        hidden fields a challenge's state carries -- safe, since only
        the hash is ever exposed, never the state itself.
        """
        return stable_hash(self.build_initial_state())

    def hidden_truth_hash(self) -> str:
        """Hash of this version's hidden answer key / ground truth.

        Default: hash of an empty payload, for challenges with no
        notion of a hidden answer key (e.g. the ping/counter examples).
        A challenge with real hidden truth (an expected-decisions map,
        a risk policy, etc.) should override this to hash that content.
        """
        return stable_hash({})

    def scoring_rules_hash(self) -> str:
        """Hash of this version's scoring rubric.

        Default: hash of `scoring_weight_overrides()` (`None` means
        "use the engine's own defaults", which still hashes stably).
        """
        return stable_hash(self.scoring_weight_overrides())

    def manifest(self) -> ChallengeManifest:
        """This challenge version's full benchmark manifest."""
        return ChallengeManifest(
            challenge_id=self.id,
            version=self.version,
            dataset_hash=self.dataset_hash(),
            hidden_truth_hash=self.hidden_truth_hash(),
            scoring_rules_hash=self.scoring_rules_hash(),
            published_at=self.published_at,
            scoring_engine_version=SCORING_ENGINE_VERSION,
        )

    def describe(self) -> ChallengeDescriptor:
        """The public Challenge object served to agents (spec §7)."""
        return ChallengeDescriptor(
            id=self.id,
            name=self.name,
            version=self.version,
            time_limit_seconds=self.time_limit_seconds,
            public_instructions=self.public_instructions,
            allowed_actions=list(self.allowed_actions),
            category=self.category,
            difficulty=self.difficulty,
            estimated_duration_minutes=self.estimated_duration_minutes,
            capabilities_tested=list(self.capabilities_tested),
            description=self.description,
            recommended_agent_types=list(self.recommended_agent_types),
        )
