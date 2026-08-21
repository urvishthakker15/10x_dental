"""Small, synthetic fixtures shared by core tests."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from recall_engine.database import Database
from recall_engine.engine import RecallEngine


PATIENT_FIELDS = ["patient_id", "first_name", "last_name", "email", "provider", "status", "is_active"]
APPOINTMENT_FIELDS = ["appointment_id", "patient_id", "start_time", "cancelled", "completed"]


def patient_row(
    patient_id: str,
    *,
    provider: str = "Provider A",
    status: str = "Active",
    is_active: str = "true",
) -> dict[str, str]:
    """Build one minimal patient CSV row."""
    return {
        "patient_id": patient_id,
        "first_name": f"First{patient_id}",
        "last_name": "Patient",
        "email": f"{patient_id.lower()}@example.test",
        "provider": provider,
        "status": status,
        "is_active": is_active,
    }


def appointment_row(
    appointment_id: str,
    patient_id: str,
    start_time: str,
    *,
    cancelled: str = "false",
    completed: str = "false",
) -> dict[str, str]:
    """Build one minimal appointment CSV row."""
    return {
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "start_time": start_time,
        "cancelled": cancelled,
        "completed": completed,
    }


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    """Write a deterministic CSV fixture."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class EngineTestCase(unittest.TestCase):
    """Create an isolated engine and source files for each test."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.patients_path = self.root / "patients.csv"
        self.appointments_path = self.root / "appointments.csv"
        self.database = Database(self.root / "recall.sqlite3")
        self.engine = RecallEngine(self.database)
        self.engine.initialize()
        self.now = datetime(2026, 8, 20, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_data(self, patients: list[dict[str, str]], appointments: list[dict[str, str]]) -> None:
        """Replace both source fixtures for the next engine run."""
        write_csv(self.patients_path, PATIENT_FIELDS, patients)
        write_csv(self.appointments_path, APPOINTMENT_FIELDS, appointments)

    def load_states(self, now: datetime | None = None):
        """Refresh patient recall state from the current fixture files."""
        return self.engine.load_states(self.patients_path, self.appointments_path, now or self.now)

    def plan(self, states, now: datetime | None = None):
        """Create a weekly plan with safe test content."""
        return self.engine.plan_week(
            states,
            now or self.now,
            100,
            "Test Dental",
            "https://example.test/book",
            "https://example.test/unsubscribe",
        )


class FakeSender:
    """Capture sends without contacting an external provider."""

    def __init__(self) -> None:
        self.calls = []

    def send(self, recipient, content, idempotency_key):
        """Record one call and return a provider-like ID."""
        self.calls.append((recipient, content, idempotency_key))
        return f"fake-message-{len(self.calls)}"
