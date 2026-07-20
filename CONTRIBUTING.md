# Contributing to halu-core

Thanks for considering a contribution. This document covers the basics;
for anything not covered here, open a discussion before a large PR so
we can agree on direction first.

## Development setup

```bash
git clone https://github.com/halu-checker/halu-core.git
cd halu-core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Before opening a PR

```bash
pytest
ruff check .
mypy src/halu_core
```

All three must pass. If you add a new Alembic migration, also verify:

```bash
alembic upgrade head              # from empty
alembic upgrade <previous_head>   # then to head, from the prior revision
```

## Code style

- No comments explaining *what* code does (names should do that) —
  only comments explaining a non-obvious *why* (a hidden constraint, a
  workaround, an invariant that would surprise a reader).
- Don't add abstractions, config flags, or error handling for scenarios
  that can't happen. Trust internal invariants; validate only at
  system boundaries.
- Match the existing docstring style: a module/function docstring
  explains the *rationale*, not a restatement of the signature.

## What belongs in this repository

`halu-core` is the generic, open-source engine. It must never contain:

- An official challenge's hidden dataset or answer key.
- Production configuration or secrets.
- Admin logic or the private website's code.

If you're building a challenge with real hidden rules, it belongs in
its own package (or a private repository like `halu-web`) that depends
on `halu-core`, not inside this one. The two bundled example challenges
(`example_ping_001`, `example_counter_001`) are deliberately trivial and
must stay that way — they exist purely to document the `Challenge`
protocol.

## Tests

Every behavioral change needs a test. Follow the existing pattern for
new features: a pure unit test for the logic itself, an integration
test through the Agent API (`fastapi.testclient.TestClient`) when it's
reachable over HTTP, and — for anything touching the challenge
registry — a test using a small local stand-in challenge rather than a
real one (core's own tests never depend on `halu-web`).

## Reporting bugs

Open a GitHub issue with: what you expected, what happened instead, and
the smallest reproduction you can manage. For suspected security
issues, see [`SECURITY.md`](SECURITY.md) instead — don't open a public
issue.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By
participating, you're expected to uphold it.
