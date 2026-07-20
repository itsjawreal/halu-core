"""Challenge registry: where challenge implementations become discoverable.

Any package -- including halu-web, or a third-party package that only
depends on halu-core -- can register a challenge without modifying this
module or any other halu-core code:

    from halu_core.challenges.registry import registry
    registry.register(MyChallenge())

`registry` is a process-wide singleton so that every part of the app
(the Agent API, the CLI, tests) sees the same set of registered
challenges once the packages defining them have been imported.

Challenges are keyed by `(id, version)`, not `id` alone: two versions of
the same challenge id can be registered and stay resolvable at the same
time, so a `Run` pinned to an older `challenge_version` keeps working
after a newer version of that challenge is registered (see
`halu_core.api.agent._resolve_challenge`, which always resolves a run's
*exact* pinned version rather than "whatever is currently registered").
`get`/`is_registered`/`unregister` without an explicit `version` operate
on the most-recently-registered version for that id, for callers (the
website's challenge picker, most tests) that only care about "the
current one".
"""

from __future__ import annotations

from halu_core.challenges.base import Challenge
from halu_core.challenges.quality import ChallengeQualityError, validate_challenge
from halu_core.config import settings


class ChallengeAlreadyRegisteredError(Exception):
    """A challenge with this id (and version) is already registered."""


class ProductionManifestChangeError(Exception):
    """`allow_manifest_change=True` was passed in production.

    Explicit development/test-only replacement mode (spec Phase 8 §1):
    a production deployment must never silently accept a changed
    dataset/hidden-truth/scoring-rules manifest for an already-published
    (id, version) -- that would break reproducibility for every run
    already scored against it.
    """


class ChallengeNotFoundError(Exception):
    """No challenge is registered under this id (and version, if given)."""


class ChallengeManifestMismatchError(Exception):
    """The same (id, version) is being re-registered with a different
    dataset/hidden-truth/scoring-rules manifest (Phase 7.5: benchmark
    integrity). A version's content must not silently change once
    published; bump the version instead, or pass
    `allow_manifest_change=True` for explicit development replacement.
    """


class ChallengeRegistry:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Challenge] = {}
        self._latest_version: dict[str, str] = {}
        self._manifest_hash_by_key: dict[tuple[str, str], str] = {}

    def register(
        self,
        challenge: Challenge,
        *,
        replace: bool = False,
        skip_quality_checks: bool = False,
        allow_manifest_change: bool = False,
    ) -> None:
        """Register `challenge` under `(challenge.id, challenge.version)`.

        Raises ChallengeAlreadyRegisteredError unless `replace=True`.
        Becomes the "latest" version resolved for this id by calls that
        don't pass an explicit `version`.

        Before storing, runs automated quality checks (spec: Phase 7.5)
        and raises ChallengeQualityError if any fail -- `skip_quality_checks`
        exists only for tests that intentionally exercise a broken
        stand-in challenge. Also refuses to silently change what an
        already-registered (id, version) means: if this exact key was
        previously registered with a different dataset/hidden-truth/
        scoring-rules manifest, raises ChallengeManifestMismatchError
        unless `allow_manifest_change=True` (explicit development
        replacement mode).
        """
        if allow_manifest_change and settings.is_production:
            raise ProductionManifestChangeError(
                "allow_manifest_change=True is not permitted in production "
                f"(attempted for {challenge.id!r} version {challenge.version!r})."
            )

        if not skip_quality_checks:
            violations = validate_challenge(challenge)
            if violations:
                raise ChallengeQualityError(
                    f"Challenge {challenge.id!r} version {challenge.version!r} failed "
                    f"quality checks: {'; '.join(violations)}"
                )

        key = (challenge.id, challenge.version)
        content_hash = challenge.manifest().content_hash
        existing_hash = self._manifest_hash_by_key.get(key)
        if (
            existing_hash is not None
            and existing_hash != content_hash
            and not allow_manifest_change
        ):
            raise ChallengeManifestMismatchError(
                f"Challenge {challenge.id!r} version {challenge.version!r} is already "
                "registered with a different dataset/hidden-truth/scoring-rules "
                "manifest. Bump the version, or pass allow_manifest_change=True."
            )

        if not replace and key in self._by_key:
            raise ChallengeAlreadyRegisteredError(
                f"A challenge is already registered under id {challenge.id!r} "
                f"version {challenge.version!r}."
            )
        self._by_key[key] = challenge
        self._manifest_hash_by_key[key] = content_hash
        self._latest_version[challenge.id] = challenge.version

    def get(self, challenge_id: str, version: str | None = None) -> Challenge:
        if version is not None:
            try:
                return self._by_key[(challenge_id, version)]
            except KeyError:
                raise ChallengeNotFoundError(
                    f"No challenge is registered under id {challenge_id!r} "
                    f"version {version!r}."
                ) from None
        latest = self._latest_version.get(challenge_id)
        if latest is None:
            raise ChallengeNotFoundError(
                f"No challenge is registered under id {challenge_id!r}."
            )
        return self._by_key[(challenge_id, latest)]

    def is_registered(self, challenge_id: str, version: str | None = None) -> bool:
        if version is not None:
            return (challenge_id, version) in self._by_key
        return challenge_id in self._latest_version

    def all(self) -> list[Challenge]:
        """The latest-version instance for every registered challenge id."""
        return [self._by_key[(cid, ver)] for cid, ver in self._latest_version.items()]

    def unregister(self, challenge_id: str, version: str | None = None) -> None:
        if version is not None:
            self._by_key.pop((challenge_id, version), None)
            self._manifest_hash_by_key.pop((challenge_id, version), None)
            if self._latest_version.get(challenge_id) == version:
                remaining = sorted(v for (cid, v) in self._by_key if cid == challenge_id)
                if remaining:
                    self._latest_version[challenge_id] = remaining[-1]
                else:
                    self._latest_version.pop(challenge_id, None)
            return
        for key in [k for k in self._by_key if k[0] == challenge_id]:
            del self._by_key[key]
            self._manifest_hash_by_key.pop(key, None)
        self._latest_version.pop(challenge_id, None)


registry = ChallengeRegistry()
