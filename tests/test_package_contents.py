"""Package-content tests (Phase 8 §2, §9): the built wheel/sdist must
never contain a `halu_web` reference or any official-challenge hidden
data. `halu-core` has no idea `halu-web`'s challenges exist, so this is
mostly a static guarantee -- these tests exist to catch a regression
(e.g. someone accidentally vendoring web code into core) rather than to
discover something surprising.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "halu_core"

# Terms that only ever belong to halu-web's official (hidden-rule)
# challenges -- if any of these ever show up inside halu-core's own
# source tree, something has gone very wrong. (Generic concept names
# like "expected_decisions" are deliberately excluded: core's own
# redaction denylist legitimately references that *key name* as a
# pattern to strip, without knowing what challenge might use it.)
_FORBIDDEN_TERMS = (
    "halu_web",
    "bounty_triage_001",
    "support_triage_001",
    "trading_risk_001",
    "wallet_aaaaaaaaaaaaaaaa",
)


def test_source_tree_has_no_halu_web_or_hidden_challenge_references() -> None:
    offending: list[str] = []
    for path in _SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for term in _FORBIDDEN_TERMS:
            if term in text:
                offending.append(f"{path.relative_to(_SRC_ROOT)}: contains {term!r}")
    assert offending == []


def test_py_typed_marker_is_present() -> None:
    assert (_SRC_ROOT / "py.typed").exists()
