"""Derive patient-level effective last-visit date and missing-history status."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PRACTICE_TIMEZONE = ZoneInfo("America/Los_Angeles")
TRUE_VALUES = {"true", "1", "yes"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive patient-level effective last-visit status."
    )
    parser.add_argument("--patients", required=True, type=Path)
    parser.add_argument("--appointments", required=True, type=Path)
    parser.add_argument(
        "--as-of",
        type=datetime.fromisoformat,
        default=None,
        help="Optional ISO timestamp; defaults to the current Pacific Time.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for a patient-level CSV result.",
    )
    return parser.parse_args()


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_VALUES


def in_practice_timezone(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(PRACTICE_TIMEZONE)


def main() -> None:
    args = parse_args()
    if not args.patients.is_file() or not args.appointments.is_file():
        raise FileNotFoundError("Both --patients and --appointments must point to files.")

    as_of = args.as_of
    if as_of is None:
        as_of = datetime.now(PRACTICE_TIMEZONE)
    elif as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=PRACTICE_TIMEZONE)
    else:
        as_of = as_of.astimezone(PRACTICE_TIMEZONE)

    appointment_evidence: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "future_non_cancelled": [],
            "past_completed": [],
        }
    )
    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            patient_id = row["patient_id"]
            start_time = in_practice_timezone(row["start_time"])
            evidence = appointment_evidence[patient_id]
            if start_time > as_of and not is_true(row.get("cancelled")):
                evidence["future_non_cancelled"].append(start_time)
            elif start_time <= as_of and is_true(row.get("completed")):
                evidence["past_completed"].append(start_time)

    output_rows: list[dict[str, str]] = []
    history_status_counts = Counter()
    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for patient in csv.DictReader(csv_file):
            patient_id = patient["patient_id"]
            has_appointment_records = patient_id in appointment_evidence
            evidence = appointment_evidence[patient_id]
            future_bookings = evidence["future_non_cancelled"]
            completed_visits = evidence["past_completed"]

            if future_bookings:
                effective_date = min(future_bookings)
                history_status = "not_applicable"
            elif completed_visits:
                effective_date = max(completed_visits)
                history_status = "not_applicable"
            else:
                effective_date = None
                history_status = (
                    "no_appointment_records"
                    if not has_appointment_records
                    else "appointment_records_but_no_completed_or_future_booking"
                )

            history_status_counts[history_status] += 1
            output_rows.append(
                {
                    "patient_id": patient_id,
                    "is_active": patient["is_active"],
                    "effective_last_visit_date": (
                        effective_date.date().isoformat() if effective_date else ""
                    ),
                    "history_status": history_status,
                }
            )

    print(f"As of: {as_of.isoformat()}")
    print("\nHistory status")
    for status, count in history_status_counts.most_common():
        print(f"  {status:<58} {count:>6,}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=output_rows[0].keys())
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"\nWrote patient-level result: {args.output}")


if __name__ == "__main__":
    main()
