"""Challenge benchmark manifest (Phase 7.5): content hashes and version
metadata that let a run's scoring stay reproducible even as challenges
evolve.

Only hashes, the version string, and timestamps are ever exposed
publicly through a `ChallengeManifest` -- never the hidden dataset or
answer key content itself. A challenge's `dataset_hash()`/
`hidden_truth_hash()`/`scoring_rules_hash()` hooks (see `base.Challenge`)
hash that private content internally; this module never sees the
plaintext of any of it beyond whatever a given challenge chooses to hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# Bumped when the scoring *engine* itself changes in a way that could
# alter a score's meaning (verdict rules, reliability/honesty formulas,
# weighting) -- independent of any single challenge's own version.
SCORING_ENGINE_VERSION = "v2"


def stable_hash(payload: Any) -> str:
    """A deterministic SHA-256 hex digest of any JSON-serializable value.

    `sort_keys=True` makes key order irrelevant; `default=str` lets
    non-JSON-native values (e.g. enums) hash consistently rather than
    raising, since every dataset is happy to be stringified.
    """
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ChallengeManifest:
    """Benchmark integrity metadata for one (challenge id, version) pair."""

    challenge_id: str
    version: str
    dataset_hash: str
    hidden_truth_hash: str
    scoring_rules_hash: str
    published_at: str
    scoring_engine_version: str

    @property
    def content_hash(self) -> str:
        """Hash of only the content that must not silently change under a
        fixed (id, version): dataset + hidden truth + scoring rules.

        `published_at` and `scoring_engine_version` are excluded -- the
        engine can legitimately advance without changing what this
        specific challenge version's dataset/answer-key/rubric mean, and
        `published_at` is purely informational.
        """
        return stable_hash(
            {
                "dataset_hash": self.dataset_hash,
                "hidden_truth_hash": self.hidden_truth_hash,
                "scoring_rules_hash": self.scoring_rules_hash,
            }
        )

    def to_public_dict(self) -> dict[str, str]:
        """The shape ever exposed to a run/website -- hashes and version
        info only, never the hidden content those hashes were computed
        from."""
        return {
            "challenge_id": self.challenge_id,
            "version": self.version,
            "dataset_hash": self.dataset_hash,
            "hidden_truth_hash": self.hidden_truth_hash,
            "scoring_rules_hash": self.scoring_rules_hash,
            "published_at": self.published_at,
            "scoring_engine_version": self.scoring_engine_version,
        }
