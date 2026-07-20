"""Runtime configuration for the halu-core engine.

Values are read from environment variables (see .env.example). No paid API
keys are required or read here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_SQLITE_MEMORY_URLS = ("sqlite://", "sqlite:///:memory:")


@dataclass(frozen=True)
class Settings:
    env: str
    data_dir: str
    database_url: str
    base_url: str
    default_run_ttl_seconds: int
    token_byte_length: int
    rate_limit_read_per_minute: int
    rate_limit_write_per_minute: int
    rate_limit_window_seconds: int
    view_token_ttl_seconds: int
    # Abuse protection (Phase 8 §7).
    max_run_ttl_seconds: int
    max_actions_per_run: int
    max_final_report_length: int
    max_claims_per_report: int
    max_json_depth: int
    # Data retention (Phase 8 §5), in days. 0 disables that bucket's
    # cleanup entirely (nothing in it is ever auto-deleted).
    retention_incomplete_run_days: int
    retention_completed_run_days: int
    retention_public_share_days: int
    retention_event_days: int
    retention_expired_token_days: int

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def database_is_ephemeral_sqlite(self) -> bool:
        """True only for the in-memory SQLite URL tests/dev use.

        Only this case is safe to auto-create tables for at startup; any
        persistent database (file-based SQLite, Postgres, ...) is
        expected to already be migrated via Alembic (spec §7, Phase 6.5).
        """
        return self.database_url in _SQLITE_MEMORY_URLS


class ConfigError(ValueError):
    """Settings are invalid or unsafe for the configured environment."""


def _validate(settings: Settings) -> None:
    if not settings.is_production:
        return
    problems = []
    if settings.database_url in _SQLITE_MEMORY_URLS:
        problems.append("HALU_CORE_DATABASE_URL must not be an in-memory SQLite URL.")
    if "localhost" in settings.base_url or "127.0.0.1" in settings.base_url:
        problems.append("HALU_CORE_BASE_URL still points at localhost.")
    if not settings.base_url.startswith("https://"):
        problems.append("HALU_CORE_BASE_URL must use https:// in production.")
    if settings.token_byte_length < 32:
        problems.append("HALU_CORE_TOKEN_BYTES must be at least 32 in production.")
    if problems:
        formatted = "\n  - ".join(problems)
        raise ConfigError(f"Invalid production configuration:\n  - {formatted}")


def load_settings() -> Settings:
    data_dir = os.environ.get("HALU_CORE_DATA_DIR", "./data")
    settings = Settings(
        env=os.environ.get("HALU_CORE_ENV", "development"),
        data_dir=data_dir,
        database_url=os.environ.get(
            "HALU_CORE_DATABASE_URL", f"sqlite:///{data_dir}/halu_core.db"
        ),
        base_url=os.environ.get("HALU_CORE_BASE_URL", "http://127.0.0.1:8000"),
        default_run_ttl_seconds=int(os.environ.get("HALU_CORE_RUN_TTL_SECONDS", str(30 * 60))),
        token_byte_length=int(os.environ.get("HALU_CORE_TOKEN_BYTES", "32")),
        rate_limit_read_per_minute=int(
            os.environ.get("HALU_CORE_RATE_LIMIT_READ_PER_MINUTE", "120")
        ),
        rate_limit_write_per_minute=int(
            os.environ.get("HALU_CORE_RATE_LIMIT_WRITE_PER_MINUTE", "60")
        ),
        rate_limit_window_seconds=int(
            os.environ.get("HALU_CORE_RATE_LIMIT_WINDOW_SECONDS", "60")
        ),
        view_token_ttl_seconds=int(
            os.environ.get("HALU_CORE_VIEW_TOKEN_TTL_SECONDS", str(7 * 24 * 60 * 60))
        ),
        max_run_ttl_seconds=int(
            os.environ.get("HALU_CORE_MAX_RUN_TTL_SECONDS", str(24 * 60 * 60))
        ),
        max_actions_per_run=int(os.environ.get("HALU_CORE_MAX_ACTIONS_PER_RUN", "500")),
        max_final_report_length=int(
            os.environ.get("HALU_CORE_MAX_FINAL_REPORT_LENGTH", "20000")
        ),
        max_claims_per_report=int(os.environ.get("HALU_CORE_MAX_CLAIMS_PER_REPORT", "100")),
        max_json_depth=int(os.environ.get("HALU_CORE_MAX_JSON_DEPTH", "20")),
        retention_incomplete_run_days=int(
            os.environ.get("HALU_CORE_RETENTION_INCOMPLETE_RUN_DAYS", "7")
        ),
        retention_completed_run_days=int(
            os.environ.get("HALU_CORE_RETENTION_COMPLETED_RUN_DAYS", "90")
        ),
        retention_public_share_days=int(
            os.environ.get("HALU_CORE_RETENTION_PUBLIC_SHARE_DAYS", "365")
        ),
        retention_event_days=int(os.environ.get("HALU_CORE_RETENTION_EVENT_DAYS", "90")),
        retention_expired_token_days=int(
            os.environ.get("HALU_CORE_RETENTION_EXPIRED_TOKEN_DAYS", "30")
        ),
    )
    _validate(settings)
    return settings


settings = load_settings()
