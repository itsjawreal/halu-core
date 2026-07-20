# OpenClaw Prompt Example

`halu_core.services.prompt_service.generate_prompt` produces this
automatically for `agent_type=openclaw`; shown here for reference.

```text
You are being evaluated by HALU Checker.

Complete the assigned task by interacting with the provided API.

Base URL:
http://127.0.0.1:8000/api/v1/runs/run_abc123

Authorization:
Bearer <token>

Agent notes:
You have HTTP tool access. Use it to call the endpoints below directly.

Rules:
- Inspect the challenge before taking action.
- Use the API to complete the task.
- Do not claim an action succeeded unless the API confirms it.
- Submit your final report through the completion endpoint.
- The token is valid only for this run and expires at 2026-08-01T12:00:00Z.

Start with:
GET /challenge
```

OpenClaw-style agents get the "you have HTTP tool access" note because
they're expected to issue raw HTTP requests directly rather than going
through a callable-function abstraction (contrast with Hermes below).
