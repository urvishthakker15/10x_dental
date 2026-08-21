"""Produce data-backed inputs for the Part B pacing algorithm."""

from __future__ import annotations

import argparse
import calendar
import csv
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
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


def monday_of(value: date) -> date:
    return value - timedelta(days=value.weekday())


def overdue_segment(last_completed: date, as_of: date) -> str | None:
    if as_of <= add_calendar_months(last_completed, 6):
        return None
    if as_of <= add_calendar_months(last_completed, 9):
        return "hot_6_to_9_months"
    if as_of <= add_calendar_months(last_completed, 18):
        return "warm_9_to_18_months"
    if as_of <= add_calendar_months(last_completed, 36):
        return "cold_18_to_36_months"
    return "very_cold_over_36_months"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze pacing inputs for recall outreach.")
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
    active_patient_ids: set[str] = set()
    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if (
                is_true(row.get("is_active"))
                and (row.get("status") or "").strip().lower() == "active"
                and (row.get("provider") or "").strip()
            ):
                active_patient_ids.add(row["patient_id"])

    completed: dict[str, list[date]] = defaultdict(list)
    future_bookings: dict[str, list[date]] = defaultdict(list)
    weekly_completed = Counter()
    throughput_start = args.as_of_date - timedelta(days=363)

    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            patient_id = row["patient_id"]
            if patient_id not in active_patient_ids:
                continue
            appointment_date = datetime.fromisoformat(row["start_time"]).astimezone(
                PRACTICE_TIMEZONE
            ).date()
            if appointment_date <= args.as_of_date and is_true(row.get("completed")):
                completed[patient_id].append(appointment_date)
                if appointment_date >= throughput_start:
                    weekly_completed[monday_of(appointment_date)] += 1
            elif appointment_date > args.as_of_date and not is_true(row.get("cancelled")):
                future_bookings[patient_id].append(appointment_date)

    backlog_segments = Counter()
    projected_inflow_month = Counter()
    future_booked = 0
    no_history = 0
    for patient_id in active_patient_ids:
        patient_completed = sorted(set(completed[patient_id]))
        if future_bookings[patient_id]:
            future_booked += 1
            continue
        if not patient_completed:
            no_history += 1
            continue
        last_completed = patient_completed[-1]
        segment = overdue_segment(last_completed, args.as_of_date)
        if segment:
            backlog_segments[segment] += 1
        else:
            due_date = add_calendar_months(last_completed, 6)
            if due_date <= add_calendar_months(args.as_of_date, 12):
                projected_inflow_month[due_date.strftime("%Y-%m")] += 1

    observed_events_month = Counter()
    historical_start = add_calendar_months(args.as_of_date, -12)
    for patient_id in active_patient_ids:
        patient_completed = sorted(set(completed[patient_id]))
        for index, visit_date in enumerate(patient_completed):
            due_date = add_calendar_months(visit_date, 6)
            next_completed = (
                patient_completed[index + 1] if index + 1 < len(patient_completed) else None
            )
            became_overdue = next_completed is None and not future_bookings[patient_id] and args.as_of_date > due_date
            if next_completed and next_completed > due_date:
                became_overdue = True
            if became_overdue and historical_start < due_date <= args.as_of_date:
                observed_events_month[due_date.strftime("%Y-%m")] += 1

    weeks = [throughput_start + timedelta(days=7 * index) for index in range(52)]
    weekly_values = [weekly_completed[monday_of(week)] for week in weeks]

    print(f"As of date: {args.as_of_date.isoformat()}")
    print(f"Active patients with valid provider/status: {len(active_patient_ids):,}")
    print("\nCurrent confirmed overdue backlog")
    for segment in (
        "hot_6_to_9_months",
        "warm_9_to_18_months",
        "cold_18_to_36_months",
        "very_cold_over_36_months",
    ):
        print(f"  {segment:<32} {backlog_segments[segment]:>6,}")
    print(f"  {'total_confirmed_backlog':<32} {sum(backlog_segments.values()):>6,}")
    print(f"  {'future_booked':<32} {future_booked:>6,}")
    print(f"  {'no_history':<32} {no_history:>6,}")

    print("\nObserved newly-overdue events in the trailing 12 months")
    for month, count in sorted(observed_events_month.items()):
        print(f"  {month}: {count:,}")
    observed_total = sum(observed_events_month.values())
    print(f"  trailing_12_month_total: {observed_total:,}")
    print(f"  average_per_month: {observed_total / 12:.1f}")
    print(f"  average_per_week: {observed_total / 52:.1f}")

    print("\nProjected due dates for currently on-time, unbooked patients")
    for month, count in sorted(projected_inflow_month.items()):
        print(f"  {month}: {count:,}")
    projected_total = sum(projected_inflow_month.values())
    print(f"  next_12_month_total: {projected_total:,}")
    print(f"  average_per_month: {projected_total / 12:.1f}")
    print(f"  average_per_week: {projected_total / 52:.1f}")

    print("\nCompleted-appointment throughput proxy (trailing 52 weeks)")
    print(f"  total_completed_appointments: {sum(weekly_values):,}")
    print(f"  average_per_week: {statistics.fmean(weekly_values):.1f}")
    print(f"  median_per_week: {statistics.median(weekly_values):.1f}")
    print(f"  min_to_max_per_week: {min(weekly_values):,}–{max(weekly_values):,}")


if __name__ == "__main__":
    main()
