# Security Policy

## Reporting a vulnerability

Please report security issues privately — **do not** open a public
GitHub issue for a suspected vulnerability. Email the maintainers (see
the repository's GitHub profile for current contact details) with:

- A description of the issue and its potential impact.
- Steps to reproduce, or a proof-of-concept if you have one.
- The version/commit you tested against.

We aim to acknowledge reports within 5 business days and to agree on a
disclosure timeline with the reporter before anything is made public.
Please give us a reasonable window to investigate and ship a fix before
any public disclosure or write-up.

## Supported versions

This project is in public alpha (pre-1.0). Security fixes land on the
latest released minor version; older versions are not separately
patched.

## Scope

In scope: `halu_core` itself — the run/token lifecycle, the Agent API,
the challenge registry/quality checks, the scoring engine, data
retention/cleanup, and the CLI.

Out of scope: vulnerabilities in third-party dependencies (report those
upstream), and the private `halu-web` repository's official challenge
datasets/answer keys (a different threat model — that repository is not
public).

## Threat model

**We assume:**
- An **untrusted agent** under evaluation. It may hallucinate, lie in
  its final report, or follow prompt-injection text embedded in
  challenge content. The entire scoring engine exists because of this
  assumption — see `docs/scoring-extension.md`.
- An **untrusted public internet** for any deployment exposed to it:
  automated abuse (credential stuffing against tokens, scraping,
  scripted mass run creation), which is why rate limiting, max-active-
  runs-per-IP, a create-run honeypot, and request-size/depth limits all
  exist.
- A challenge author who might make mistakes (leaking a hidden field, an
  invalid scoring rubric, non-deterministic state) — the registry's
  automated quality checks exist to catch this at registration time,
  loudly, rather than silently corrupting results later.

**We do not currently assume:**
- A fully compromised production database is an acceptable baseline —
  token/manifest hashing is defense-in-depth for that scenario, not a
  substitute for actually securing the database, network, and host.
- A malicious *operator* running their own deployment — this project
  trusts whoever controls the environment variables and the database.

## Security properties enforced today

- Every token (`RunToken`, `RunViewToken`, `RunPublicShare`) is scoped
  to exactly one run, stored only as a SHA-256 hash, and rejected once
  its run expires, is revoked, or (for the agent token) completes.
- A completed run's agent token is permanently disabled; a second
  completion attempt, or any action after completion, is rejected
  consistently regardless of endpoint.
- Structured, sanitized logging never includes a raw token or hidden
  challenge data (`halu_core.security.redaction`).
- Security headers (CSP, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, frame protection) are applied to every response
  `create_app()` builds.
- Request bodies are size- and depth-limited
  (`MaxBodySizeMiddleware`, `halu_core.security.json_limits`).
- In production, run creation fails outright if a challenge's benchmark
  manifest can't be built, and challenge registration refuses to
  silently change an already-published version's content.
