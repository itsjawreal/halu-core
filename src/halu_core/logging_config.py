"""Structured application logging (Phase 6.5 §9).

Every log line is a single JSON object with a stable set of fields, so
logs are grep/parse-friendly regardless of destination (stdout in
prod, pytest's capture in tests). Configured once, idempotently, from
`create_app()`.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_CONFIGURED = False
_EXTRA_FIELDS = (
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    # Phase 8 §6: run-related log lines identify which challenge
    # (id/version) a request concerns -- never the run's token, and
    # never any hidden challenge data, only these two public strings.
    "challenge_id",
    "challenge_version",
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    _CONFIGURED = True


access_logger = logging.getLogger("halu_core.access")
error_logger = logging.getLogger("halu_core.errors")
operational_logger = logging.getLogger("halu_core.operational")
