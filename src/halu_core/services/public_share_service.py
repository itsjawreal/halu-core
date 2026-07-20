"""Public result sharing (Phase 8 §4): an opaque, read-only link a run's
owner (proven by holding its private view token) can turn on or off.

Entirely separate from the agent's bearer token and the private view
token -- enabling or using a public share never reads, rotates, or
exposes either. Only a completed run may be shared; the public page
this backs is expected to show sanitized result/receipt/manifest data
only, never raw events or an unredacted final report (that policy lives
in halu-web's public share route, not here).
"""

from __future__ import annotations

from sqlmodel import Session, col, select

from halu_core.models.public_share import RunPublicShare
from halu_core.models.run import Run
from halu_core.services.token_service import generate_raw_token, hash_token
from halu_core.timeutils import utc_now

_SLUG_BYTE_LENGTH = 24


def _active_share(session: Session, run_id: str) -> RunPublicShare | None:
    return session.exec(
        select(RunPublicShare)
        .where(RunPublicShare.run_id == run_id, col(RunPublicShare.enabled).is_(True))
        .order_by(col(RunPublicShare.created_at).desc())
    ).first()


def create_public_share(session: Session, run_id: str) -> str:
    """Enable public sharing for `run_id`, returning the raw slug.

    If a share is already enabled, disables it first (so at most one
    slug is ever active for a run at a time) and records the new one as
    rotated from the old.
    """
    existing = _active_share(session, run_id)
    if existing is not None:
        existing.enabled = False
        existing.disabled_at = utc_now()
        session.add(existing)

    raw_slug = generate_raw_token(_SLUG_BYTE_LENGTH)
    share = RunPublicShare(
        run_id=run_id,
        slug_hash=hash_token(raw_slug),
        enabled=True,
        rotated_from_id=existing.id if existing is not None else None,
    )
    session.add(share)
    session.commit()
    return raw_slug


def rotate_public_share(session: Session, run_id: str) -> str:
    """Disable the current share (if any) and issue a fresh one.

    The old slug stops resolving immediately; only the newly returned
    raw slug works afterwards.
    """
    return create_public_share(session, run_id)


def disable_public_share(session: Session, run_id: str) -> bool:
    """Disable every currently-active public share for `run_id`.

    Returns True if at least one share was disabled.
    """
    active = session.exec(
        select(RunPublicShare).where(
            RunPublicShare.run_id == run_id, col(RunPublicShare.enabled).is_(True)
        )
    ).all()
    if not active:
        return False
    now = utc_now()
    for share in active:
        share.enabled = False
        share.disabled_at = now
        session.add(share)
    session.commit()
    return True


def is_public_sharing_enabled(session: Session, run_id: str) -> bool:
    return _active_share(session, run_id) is not None


def get_run_by_public_slug(session: Session, raw_slug: str) -> Run | None:
    """Resolve a public share slug to its run.

    Only returns a run whose share is currently enabled -- a disabled/
    rotated-away slug resolves to nothing, same as if it never existed
    (no distinguishing "revoked" from "never existed" to a stranger).
    Does not check run status; callers decide what to show for a run
    that isn't completed yet (same convention as the private view-token
    pages).
    """
    share = session.exec(
        select(RunPublicShare).where(
            RunPublicShare.slug_hash == hash_token(raw_slug), col(RunPublicShare.enabled).is_(True)
        )
    ).first()
    if share is None:
        return None
    return session.get(Run, share.run_id)
