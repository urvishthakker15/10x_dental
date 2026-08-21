"""Calculate Part A question 1: post-healthy-cadence lapse rate."""

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
        description="Calculate the post-healthy-cadence overdue rate."
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
    completed_visits: dict[str, list[date]] = defaultdict(list)
    future_bookings: dict[str, list[date]] = defaultdict(list)

    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            appointment_date = datetime.fromisoformat(row["start_time"]).astimezone(
                PRACTICE_TIMEZONE
            ).date()
            patient_id = row["patient_id"]
            if appointment_date <= args.as_of_date and is_true(row.get("completed")):
                completed_visits[patient_id].append(appointment_date)
            elif appointment_date > args.as_of_date and not is_true(row.get("cancelled")):
                future_bookings[patient_id].append(appointment_date)

    active_patient_ids: set[str] = set()
    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            # Apply the documented data-quality exclusions for missing provider
            # and status while retaining the active-patient denominator.
            if (
                is_true(row.get("is_active"))
                and (row.get("provider") or "").strip()
                and (row.get("status") or "").strip()
            ):
                active_patient_ids.add(row["patient_id"])

    opportunities = 0
    lapses = 0
    episodes = 0
    activated_patients = 0
    censored_final_intervals = 0
    open_lapses = 0

    for patient_id in active_patient_ids:
        completed = sorted(set(completed_visits[patient_id]))
        future = min(future_bookings[patient_id], default=None)
        if len(completed) < 2:
            continue

        patient_activated = False
        index = 1
        in_episode = False

        while index < len(completed):
            previous_visit = completed[index - 1]
            current_visit = completed[index]

            if not in_episode:
                if current_visit <= add_calendar_months(previous_visit, 6):
                    in_episode = True
                    episodes += 1
                    patient_activated = True
                index += 1
                continue

            # An active episode evaluates the interval ending at the current
            # completed visit. A lapse ends the episode; a later pair of
            # on-time completed visits can start another one.
            opportunities += 1
            if current_visit > add_calendar_months(previous_visit, 6):
                lapses += 1
                in_episode = False
            index += 1

        if patient_activated:
            activated_patients += 1

        if not in_episode:
            continue

        last_completed = completed[-1]
        if future is not None:
            opportunities += 1
            if future > add_calendar_months(last_completed, 6):
                lapses += 1
            continue

        if args.as_of_date > add_calendar_months(last_completed, 6):
            opportunities += 1
            lapses += 1
            open_lapses += 1
        else:
            censored_final_intervals += 1

    rate = lapses / opportunities if opportunities else 0
    print(f"As of date: {args.as_of_date.isoformat()}")
    print(f"Active patients included: {len(active_patient_ids):,}")
    print(f"Patients ever entering healthy cadence: {activated_patients:,}")
    print(f"Healthy-cadence episodes: {episodes:,}")
    print(f"Observed post-cadence opportunities: {opportunities:,}")
    print(f"Post-cadence lapses: {lapses:,}")
    print(f"Open lapses as of analysis date: {open_lapses:,}")
    print(f"Censored final intervals: {censored_final_intervals:,}")
    print(f"Post-healthy-cadence lapse rate: {rate:.2%}")


if __name__ == "__main__":
    main()
