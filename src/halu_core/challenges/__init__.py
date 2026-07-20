"""Challenge engine: protocol, registry, and no-hidden-logic examples.

Importing this package registers halu-core's own example challenges into
`halu_core.challenges.registry.registry`. Official, scored challenges
(with hidden validation rules) live in halu-web and are registered when
*that* package is imported instead.
"""

from __future__ import annotations

from halu_core.challenges import examples  # noqa: F401
from halu_core.challenges.base import Challenge
from halu_core.challenges.models import ActionRequest, ActionResult, ChallengeDescriptor
from halu_core.challenges.registry import (
    ChallengeAlreadyRegisteredError,
    ChallengeNotFoundError,
    ChallengeRegistry,
    registry,
)

__all__ = [
    "Challenge",
    "ActionRequest",
    "ActionResult",
    "ChallengeDescriptor",
    "ChallengeRegistry",
    "ChallengeAlreadyRegisteredError",
    "ChallengeNotFoundError",
    "registry",
]
