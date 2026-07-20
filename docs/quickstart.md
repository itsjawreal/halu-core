# Quick-start: Self-Hosting

## 1. Install

```bash
git clone https://github.com/halu-checker/halu-core.git
cd halu-core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## 2. Choose a database

Development/tests use an ephemeral in-memory SQLite database by
default (`HALU_CORE_DATABASE_URL=sqlite://`) — nothing to set up.

For anything persistent (a real deployment, or just wanting your data
to survive a restart), point at a file or Postgres and run migrations
first:

```bash
export HALU_CORE_DATABASE_URL=postgresql://user:pass@localhost/halu_core
alembic upgrade head
```

`create_app()`'s startup **never** auto-creates a persistent database's
schema — only the ephemeral in-memory URL gets that convenience. Any
other `HALU_CORE_DATABASE_URL` must already be migrated, or the app
refuses to consider itself ready (`GET /health/ready` reports
`migration_head: false`).

## 3. Run it

```bash
uvicorn halu_core.main:app --reload
```

```bash
curl http://127.0.0.1:8000/health/live    # process is up
curl http://127.0.0.1:8000/health/ready   # DB + migrations + challenges OK
```

## 4. Create a run

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"challenge_id": "example_ping_001", "agent_type": "generic"}'
```

Bundled example challenges (`example_ping_001`, `example_counter_001`)
are deliberately trivial and trap-free — they exist to document the
protocol, not to evaluate anything. Register your own challenge (see
[`custom-challenge-tutorial.md`](custom-challenge-tutorial.md)) or
depend on `halu-web`'s official ones for real evaluation.

## 5. Production configuration

Setting `HALU_CORE_ENV=production` turns on stricter validation at
import time (`config.py`): the database must not be in-memory SQLite,
`HALU_CORE_BASE_URL` must be `https://` and not point at localhost,
and the token byte length must be at least 32. Production mode also:

- makes run creation **fail** if a challenge's benchmark manifest can't
  be built (no more best-effort "unversioned" runs), and
- refuses `allow_manifest_change=True` at challenge registration.

See [`.env.example`](../.env.example) for every setting.

## 6. Cleanup / retention

```bash
halu-checker cleanup --dry-run   # report what would be deleted
halu-checker cleanup             # actually delete it
```

Retention windows (incomplete runs, completed runs, public shares,
events, expired tokens) are all configurable via `HALU_CORE_RETENTION_*`
environment variables. A completed run with an active public share is
never deleted, regardless of age.
