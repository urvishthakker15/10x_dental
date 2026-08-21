"""Calculate rolling 12-month retention from completed appointment history."""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate rolling 12-month patient retention."
    )
    parser.add_argument("--patients", required=True, type=Path)
    parser.add_argument("--appointments", required=True, type=Path)
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=datetime.now(PRACTICE_TIMEZONE).date(),
        help="End of the rolling 12-month observation window; defaults to today.",
    )
    return parser.parse_args()


def add_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def main() -> None:
    args = parse_args()
    active_patient_ids: set[str] = set()
    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if (
                is_true(row.get("is_active"))
                and (row.get("status") or "").strip().lower() == "active"
            ):
                active_patient_ids.add(row["patient_id"])

    completed_dates: dict[str, list[date]] = defaultdict(list)
    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            patient_id = row["patient_id"]
            if patient_id not in active_patient_ids or not is_true(row.get("completed")):
                continue
            appointment_date = datetime.fromisoformat(row["start_time"]).astimezone(
                PRACTICE_TIMEZONE
            ).date()
            if appointment_date <= args.as_of_date:
                completed_dates[patient_id].append(appointment_date)

    window_start = add_calendar_months(args.as_of_date, -12)
    served_in_window = {
        patient_id
        for patient_id, dates in completed_dates.items()
        if any(window_start <= appointment_date <= args.as_of_date for appointment_date in dates)
    }
    first_observed_service_in_window = {
        patient_id
        for patient_id in served_in_window
        if min(completed_dates[patient_id]) >= window_start
    }
    retained_patients = served_in_window - first_observed_service_in_window
    retention_rate = len(retained_patients) / len(served_in_window) if served_in_window else 0

    print(f"Rolling 12-month window: {window_start.isoformat()} to {args.as_of_date.isoformat()}")
    print(f"Active patients eligible for analysis: {len(active_patient_ids):,}")
    print(f"Unique active patients served in window: {len(served_in_window):,}")
    print(
        "Patients whose first observed completed visit was in window: "
        f"{len(first_observed_service_in_window):,}"
    )
    print(f"Retained patients: {len(retained_patients):,}")
    print(f"Rolling 12-month retention rate: {retention_rate:.2%}")


if __name__ == "__main__":
    main()
