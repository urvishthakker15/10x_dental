"""Small typed schemas used at the system boundary and in core decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass(frozen=True)
class PatientRecord:
    patient_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    provider: str
    status: str
    is_active: bool


@dataclass(frozen=True)
class AppointmentRecord:
    appointment_id: str
    patient_id: str
    start_at: datetime
    cancelled: bool
    completed: bool


@dataclass(frozen=True)
class RecallState:
    patient: PatientRecord
    latest_completed_at: Optional[datetime]
    future_booking_at: Optional[datetime]
    due_date: Optional[date]
    segment: Optional[str]
    history_status: str


@dataclass(frozen=True)
class Candidate:
    patient_id: str
    first_name: str
    email: str
    segment: str
    pool: str
    due_date: Optional[date]
    months_since_last_visit: Optional[int] = None
    attempt_count: int = 0


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str
