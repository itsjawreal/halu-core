# halu-core

Open-source engine behind **HALU Checker** — verify what your AI agent
actually did.

`halu-core` is the reusable, self-hostable part of the platform: a
run/token lifecycle, a scoped-token security model, a generic Agent API
(challenge/context/items/actions/completion/events/result), an
event-sourced audit log, and a deterministic scoring engine that judges
task completion, action accuracy, claim honesty, tool usage, and safety
— split into **Execution Reliability** ("did the agent do the work?")
and **Reporting Honesty** ("did its final report tell the truth about
it?").

The official branded website, its hosted challenges, and their hidden
datasets/answer keys live in a separate **private** repository
(`halu-web`), which depends on this package. Nothing in this repository
ever contains hidden challenge data, an answer key, production
configuration, or admin logic — see [Security model](#security-model)
below for what that separation buys you.

## Status

Public alpha. The run/token lifecycle, Agent API, event log, scoring
engine, challenge registry (with benchmark-manifest integrity checks),
data retention/cleanup, and operational readiness endpoints are all
implemented and tested. No user accounts, billing, or public leaderboard
yet.

## Requirements

- Python 3.10+
- No paid API keys required

## Local installation

```bash
git clone https://github.com/halu-checker/halu-core.git
cd halu-core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Quick-start: self-hosting the bare engine

```bash
uvicorn halu_core.main:app --reload
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/ready
```

Create a run against one of the two bundled, trap-free example
challenges (`example_ping_001`, `example_counter_001` — real, hidden-rule
official challenges live in `halu-web`, not here):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"challenge_id": "example_ping_001", "agent_type": "generic"}'
```

The response contains a run id and a temporary, single-run bearer token.

## API usage examples

```bash
RUN_ID=run_...
TOKEN=...

# What is this challenge? What actions can I take?
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/runs/$RUN_ID/challenge

# Take an action
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "ping"}' \
  http://127.0.0.1:8000/api/v1/runs/$RUN_ID/actions

# Submit a final report with structured claims
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"summary": "Pinged once.", "claims": [{"type": "task_completed", "value": true}]}' \
  http://127.0.0.1:8000/api/v1/runs/$RUN_ID/complete

# Read the scored result (works even though the agent's own token is
# revoked on completion -- see docs/api-usage.md)
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/runs/$RUN_ID/result
```

### Agent prompt examples

**OpenClaw** (HTTP tool access):

```text
You have HTTP tool access. Call GET http://127.0.0.1:8000/api/v1/runs/{run_id}/challenge
with header "Authorization: Bearer {token}" to see your task, then use the
actions it describes.
```

**Hermes** (callable-function style):

```text
Use your callable-function interface to call the HALU Checker Agent API
at http://127.0.0.1:8000/api/v1/runs/{run_id}/..., authenticating every
call with "Authorization: Bearer {token}".
```

See `docs/prompts/` for the full, agent-specific prompt templates this
project's own `prompt_service` generates.

## Embedding in another app

```python
from halu_core.app import create_app

app = create_app(
    title="My HALU Checker deployment",
    readiness_challenge_ids=("my_challenge_001",),
)
# app.include_router(my_own_web_router)
```

This is exactly how `halu-web` builds the official site: it imports
`create_app()` and layers its own branded routes and official
challenges on top.

## Writing a custom challenge

See `docs/custom-challenge-tutorial.md` for a full walkthrough, and
`docs/challenge-contract.md` for the `Challenge` protocol reference.
Short version:

```python
from halu_core.challenges.base import Challenge
from halu_core.challenges.registry import registry

class MyChallenge(Challenge):
    @property
    def id(self) -> str: return "my_challenge_001"
    # ... implement the rest of the Challenge protocol ...

registry.register(MyChallenge())
```

Registering runs automated quality checks (metadata completeness,
deterministic initial state, no leaked internal keys, valid scoring
weights) and refuses to silently change an already-published version's
dataset/answer-key/scoring-rubric hash — see
`docs/challenge-contract.md` and `docs/scoring-extension.md`.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — how the pieces fit together
- [`docs/quickstart.md`](docs/quickstart.md) — longer self-hosting walkthrough
- [`docs/api-usage.md`](docs/api-usage.md) — full Agent API reference with examples
- [`docs/custom-challenge-tutorial.md`](docs/custom-challenge-tutorial.md) — build your own challenge
- [`docs/challenge-contract.md`](docs/challenge-contract.md) — the `Challenge` protocol
- [`docs/scoring-extension.md`](docs/scoring-extension.md) — scoring weights, verdicts, manifests
- [`docs/prompts/`](docs/prompts/) — OpenClaw and Hermes prompt examples
- [`SECURITY.md`](SECURITY.md) — security policy, disclosure process, threat model
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how to contribute
- [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
- [`CHANGELOG.md`](CHANGELOG.md)

## Running the CLI

```bash
halu-checker version
halu-checker create-run --challenge-id example_ping_001 --agent-type hermes
halu-checker cleanup --dry-run
halu-checker cleanup
```

## Tests

```bash
pytest
ruff check .
mypy src/halu_core
```

## Building the package

```bash
python -m build
pip install dist/halu_core-*.whl
```

The built wheel/sdist contains only `halu_core` — no official/hidden
challenge data, no `halu_web` reference, and no production secrets ever
ship in this package (see `tests/test_package_contents.py`, which fails
CI if that ever changes).

## Security model

- Every token (agent, view, public-share) is scoped to exactly one run,
  hashed before storage, and rejected once its run expires, is revoked,
  or completes.
- A challenge's hidden dataset and answer key are never visible to core
  itself — a challenge author controls exactly what `list_items`/
  `get_item`/`get_context` expose, and the registry rejects a challenge
  whose public views leak an internal (`_`-prefixed) key.
- A benchmark manifest (dataset/hidden-truth/scoring-rules hashes,
  version, timestamp) is snapshotted onto every run at creation, so a
  run stays reproducible even if the challenge is later re-registered
  under a new version. In production, run creation fails outright
  rather than proceed without one.
- See [`SECURITY.md`](SECURITY.md) for the full threat model and how to
  report a vulnerability.

## License

MIT — see [`LICENSE`](LICENSE).
