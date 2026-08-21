"""SQLite persistence for the recurring outreach process."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    patient_id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    is_active INTEGER NOT NULL,
    source_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_suppressions (
    patient_id TEXT PRIMARY KEY REFERENCES patients(patient_id),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pacing_windows (
    window_start TEXT PRIMARY KEY,
    weekly_capacity INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL REFERENCES patients(patient_id),
    pool TEXT NOT NULL CHECK(pool IN ('confirmed', 'recontact', 'no_history')),
    segment TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'booked', 'completed_no_response', 'cancelled')),
    enrolled_at TEXT NOT NULL,
    sequence_attempt_count INTEGER NOT NULL,
    booked_at TEXT,
    sequence_completed_at TEXT,
    cooldown_until TEXT,
    cancellation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_enrollments_patient_status
    ON enrollments(patient_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_enrollment_per_patient
    ON enrollments(patient_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enrollment_id INTEGER NOT NULL REFERENCES enrollments(id),
    touch_number INTEGER NOT NULL CHECK(touch_number BETWEEN 1 AND 3),
    due_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    text_body TEXT NOT NULL,
    html_body TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending', 'sending', 'sent', 'cancelled')),
    idempotency_key TEXT NOT NULL UNIQUE,
    provider_message_id TEXT,
    sent_at TEXT,
    last_error TEXT,
    claimed_at TEXT,
    UNIQUE(enrollment_id, touch_number)
);

CREATE INDEX IF NOT EXISTS idx_messages_due
    ON messages(state, due_at);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    attempted_at TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('dry_run', 'send')),
    outcome TEXT NOT NULL,
    detail TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Commit a successful SQLite unit of work and roll back any exception."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create missing tables/indexes while preserving existing outreach state."""
        with self.connection() as connection:
            connection.executescript(SCHEMA)
            self.set_setting(connection, "paused", self.get_setting(connection, "paused", "false"))

    @staticmethod
    def now_text(now: datetime) -> str:
        """Serialize an aware timestamp consistently for SQLite comparisons."""
        return now.isoformat(timespec="seconds")

    def get_setting(self, connection: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
        """Read a persisted control value, such as the global pause flag."""
        row = connection.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def set_setting(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        """Insert or update a control value without replacing other system state."""
        connection.execute(
            """
            INSERT INTO system_settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
