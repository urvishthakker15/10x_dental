"""CSV validation and dataset-independent recall eligibility derivation."""

from __future__ import annotations

import calendar
import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .models import AppointmentRecord, PatientRecord, RecallState


PATIENT_COLUMNS = {
    "patient_id", "first_name", "last_name", "email", "provider", "status", "is_active"
}
APPOINTMENT_COLUMNS = {"appointment_id", "patient_id", "start_time", "cancelled", "completed"}


def parse_bool(value: str) -> bool:
    """Accept case-insensitive `true` or `false`; reject ambiguous values."""
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"Expected true or false, got {value!r}")
    return normalized == "true"


def parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, including the common `Z` UTC suffix."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_patients(path: Path) -> dict[str, PatientRecord]:
    """Require fields used for eligibility and email; treat phone as optional."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = PATIENT_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"patients CSV is missing required columns: {', '.join(sorted(missing))}")
        patients: dict[str, PatientRecord] = {}
        for row in reader:
            patient_id = row["patient_id"].strip()
            if not patient_id:
                continue
            patients[patient_id] = PatientRecord(
                patient_id=patient_id,
                first_name=row["first_name"].strip(),
                last_name=row["last_name"].strip(),
                email=row["email"].strip(),
                phone=(row.get("phone") or "").strip(),
                provider=row["provider"].strip(),
                status=row["status"].strip(),
                is_active=parse_bool(row["is_active"]),
            )
    return patients


def read_appointments(path: Path) -> list[AppointmentRecord]:
    """Require fields needed to distinguish completed visits and future bookings."""
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = APPOINTMENT_COLUMNS.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"appointments CSV is missing required columns: {', '.join(sorted(missing))}")
        appointments: list[AppointmentRecord] = []
        for row in reader:
            if not row["appointment_id"].strip() or not row["patient_id"].strip():
                continue
            appointments.append(
                AppointmentRecord(
                    appointment_id=row["appointment_id"].strip(),
                    patient_id=row["patient_id"].strip(),
                    start_at=parse_datetime(row["start_time"].strip()),
                    cancelled=parse_bool(row["cancelled"]),
                    completed=parse_bool(row["completed"]),
                )
            )
    return appointments


def add_calendar_months(value: date, months: int) -> date:
    """Add calendar months, clamping month-end dates such as August 31."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def recall_segment(last_visit_date: date, as_of: date) -> str | None:
    """Assign a segment from exact 6, 9, 18, and 36 calendar-month boundaries."""
    if as_of <= add_calendar_months(last_visit_date, 6):
        return None
    if as_of < add_calendar_months(last_visit_date, 9):
        return "hot"
    if as_of < add_calendar_months(last_visit_date, 18):
        return "warm"
    if as_of < add_calendar_months(last_visit_date, 36):
        return "cold"
    return "very_cold"


def calendar_months_elapsed(start: date, end: date) -> int:
    """Count complete calendar months for transparent email personalization."""
    months = (end.year - start.year) * 12 + end.month - start.month
    if months > 0 and add_calendar_months(start, months) > end:
        months -= 1
    return max(0, months)


def derive_recall_states(
    patients: dict[str, PatientRecord], appointments: Iterable[AppointmentRecord], as_of: datetime
) -> dict[str, RecallState]:
    """Derive latest completed visit, future booking, due date, and segment per patient."""
    by_patient: dict[str, list[AppointmentRecord]] = defaultdict(list)
    for appointment in appointments:
        if appointment.patient_id in patients:
            by_patient[appointment.patient_id].append(appointment)

    states: dict[str, RecallState] = {}
    for patient_id, patient in patients.items():
        records = by_patient[patient_id]
        future = [record for record in records if record.start_at > as_of and not record.cancelled]
        completed_past = [record for record in records if record.start_at <= as_of and record.completed]
        future_booking_at = min((record.start_at for record in future), default=None)
        latest_completed_at = max((record.start_at for record in completed_past), default=None)

        if latest_completed_at is None and future_booking_at is None:
            history_status = "no_appointment_records" if not records else "appointment_records_but_no_completed_or_future_booking"
        else:
            history_status = "not_applicable"

        due_date = None if latest_completed_at is None else add_calendar_months(latest_completed_at.date(), 6)
        segment = None
        if latest_completed_at is not None and future_booking_at is None:
            segment = recall_segment(latest_completed_at.date(), as_of.date())

        states[patient_id] = RecallState(
            patient=patient,
            latest_completed_at=latest_completed_at,
            future_booking_at=future_booking_at,
            due_date=due_date,
            segment=segment,
            history_status=history_status,
        )
    return states


def is_contactable(patient: PatientRecord) -> bool:
    """Require an active patient, known provider/status, and deliverable email field."""
    return (
        patient.is_active
        and patient.status.casefold() == "active"
        and bool(patient.provider)
        and bool(patient.email)
    )
