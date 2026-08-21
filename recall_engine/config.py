"""Configuration loading without a third-party runtime dependency."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Load local KEY=VALUE settings without overriding exported environment values."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    database_path: Path
    time_zone: str
    weekly_capacity: int
    resend_api_key: str | None
    email_from: str | None

    @classmethod
    def from_environment(cls, database_path: Path) -> "Settings":
        """Resolve database, pacing, timezone, and Resend settings from the environment."""
        load_dotenv(Path(".env"))
        return cls(
            database_path=database_path,
            time_zone=os.getenv("RECALL_TIME_ZONE", "America/Los_Angeles"),
            weekly_capacity=int(os.getenv("WEEKLY_ENROLLMENT_CAPACITY", "100")),
            resend_api_key=os.getenv("RESEND_API_KEY"),
            email_from=os.getenv("EMAIL_FROM"),
        )
