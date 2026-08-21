"""Calculate Part A question 2: active patients currently overdue and unbooked."""

from __future__ import annotations

import argparse
import calendar
import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PRACTICE_TIMEZONE = ZoneInfo("America/Los_Angeles")
TRUE_VALUES = {"true", "1", "yes"}


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def add_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate the currently overdue and unbooked active-patient share."
    )
    parser.add_argument("--patients", required=True, type=Path)
    parser.add_argument("--appointments", required=True, type=Path)
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=datetime.now(PRACTICE_TIMEZONE).date(),
        help="Analysis date in practice-local time; defaults to today.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    future_bookings: dict[str, list[date]] = defaultdict(list)
    completed_visits: dict[str, list[date]] = defaultdict(list)

    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            appointment_date = datetime.fromisoformat(row["start_time"]).astimezone(
                PRACTICE_TIMEZONE
            ).date()
            patient_id = row["patient_id"]
            if appointment_date > args.as_of_date and not is_true(row.get("cancelled")):
                future_bookings[patient_id].append(appointment_date)
            elif appointment_date <= args.as_of_date and is_true(row.get("completed")):
                completed_visits[patient_id].append(appointment_date)

    active_patients = 0
    overdue_and_unbooked = 0
    future_booked = 0
    no_completed_history = 0

    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for patient in csv.DictReader(csv_file):
            if not (
                is_true(patient.get("is_active"))
                and (patient.get("status") or "").strip().lower() == "active"
            ):
                continue

            active_patients += 1
            patient_id = patient["patient_id"]
            if future_bookings[patient_id]:
                future_booked += 1
                continue

            completed = completed_visits[patient_id]
            if not completed:
                no_completed_history += 1
                continue

            last_completed = max(completed)
            if args.as_of_date > add_calendar_months(last_completed, 6):
                overdue_and_unbooked += 1

    overdue_share = overdue_and_unbooked / active_patients if active_patients else 0
    print(f"As of date: {args.as_of_date.isoformat()}")
    print(f"Active patients (denominator): {active_patients:,}")
    print(f"Currently overdue and unbooked (numerator): {overdue_and_unbooked:,}")
    print(f"Currently overdue and unbooked share: {overdue_share:.2%}")
    print(f"Patients with a future non-cancelled booking: {future_booked:,}")
    print(f"Patients with no completed visit or future booking: {no_completed_history:,}")


if __name__ == "__main__":
    main()
