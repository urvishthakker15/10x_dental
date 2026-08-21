"""Simulate the agreed segmented recall-pacing policy from the CSV exports."""

from __future__ import annotations

import argparse
import calendar
import csv
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


def segment_for(overdue_since: date, on_date: date) -> str:
    if on_date <= add_calendar_months(overdue_since, 3):
        return "hot"
    if on_date <= add_calendar_months(overdue_since, 12):
        return "warm"
    if on_date <= add_calendar_months(overdue_since, 30):
        return "cold"
    return "very_cold"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate segmented recall pacing.")
    parser.add_argument("--patients", required=True, type=Path)
    parser.add_argument("--appointments", required=True, type=Path)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=datetime.now(PRACTICE_TIMEZONE).date())
    parser.add_argument("--weeks", type=int, default=104)
    parser.add_argument("--weekly-capacity", type=float, default=100)
    parser.add_argument("--conversion-rate", type=float, default=0.10)
    parser.add_argument("--sequence-plus-cooldown-weeks", type=int, default=15)
    parser.add_argument("--output", type=Path, default=Path("analysis/part_b/output/segmented_pacing_projection.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    active_ids: set[str] = set()
    with args.patients.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if is_true(row.get("is_active")) and (row.get("status") or "").strip().lower() == "active" and (row.get("provider") or "").strip():
                active_ids.add(row["patient_id"])

    completed: dict[str, list[date]] = defaultdict(list)
    future: dict[str, list[date]] = defaultdict(list)
    with args.appointments.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            patient_id = row["patient_id"]
            if patient_id not in active_ids:
                continue
            appointment_date = datetime.fromisoformat(row["start_time"]).astimezone(PRACTICE_TIMEZONE).date()
            if appointment_date <= args.as_of_date and is_true(row.get("completed")):
                completed[patient_id].append(appointment_date)
            elif appointment_date > args.as_of_date and not is_true(row.get("cancelled")):
                future[patient_id].append(appointment_date)

    # Each confirmed candidate is represented by the date they crossed six
    # months overdue, allowing its segment to age during the simulation.
    confirmed_candidates: list[date] = []
    no_history_available = 0.0
    for patient_id in active_ids:
        if future[patient_id]:
            continue
        visits = sorted(set(completed[patient_id]))
        if not visits:
            no_history_available += 1
            continue
        due_date = add_calendar_months(visits[-1], 6)
        if args.as_of_date > due_date:
            confirmed_candidates.append(due_date)
    initial_confirmed_backlog = len(confirmed_candidates)

    # Trailing historical overdue events supply a conservative weekly inflow.
    observed_events = 0
    historical_start = add_calendar_months(args.as_of_date, -12)
    for patient_id in active_ids:
        visits = sorted(set(completed[patient_id]))
        for index, visit in enumerate(visits):
            due_date = add_calendar_months(visit, 6)
            next_visit = visits[index + 1] if index + 1 < len(visits) else None
            slipped = (next_visit is not None and next_visit > due_date) or (
                next_visit is None and not future[patient_id] and args.as_of_date > due_date
            )
            if slipped and historical_start < due_date <= args.as_of_date:
                observed_events += 1
    weekly_inflow = observed_events / 52

    confirmed_capacity = args.weekly_capacity * 0.90
    recontact_capacity = args.weekly_capacity * 0.05
    no_history_capacity = args.weekly_capacity * 0.05
    quotas = {"hot": confirmed_capacity * 0.50, "warm": confirmed_capacity * 0.30, "cold": confirmed_capacity * 0.20}
    recontact_schedule: dict[int, Counter[int]] = defaultdict(Counter)
    recontact_available: Counter[int] = Counter()
    projection_rows: list[dict[str, object]] = []
    total_expected_bookings = 0.0

    for week in range(1, args.weeks + 1):
        simulation_date = args.as_of_date + timedelta(days=week * 7)
        # Fractional expected inflow is sufficient for a planning simulation.
        whole_inflow = int(weekly_inflow)
        remainder = weekly_inflow - whole_inflow
        confirmed_candidates.extend([simulation_date] * whole_inflow)
        if (week * remainder) % 1 < remainder:
            confirmed_candidates.append(simulation_date)

        recontact_available.update(recontact_schedule.pop(week, Counter()))
        by_segment: dict[str, list[date]] = defaultdict(list)
        for due_date in confirmed_candidates:
            by_segment[segment_for(due_date, simulation_date)].append(due_date)
        for candidates in by_segment.values():
            candidates.sort()

        selected_confirmed: list[date] = []
        for segment in ("hot", "warm", "cold"):
            take = min(len(by_segment[segment]), round(quotas[segment]))
            selected_confirmed.extend(by_segment[segment][:take])
            by_segment[segment] = by_segment[segment][take:]
        remaining_capacity = round(confirmed_capacity) - len(selected_confirmed)
        for segment in ("hot", "warm", "cold", "very_cold"):
            take = min(len(by_segment[segment]), remaining_capacity)
            selected_confirmed.extend(by_segment[segment][:take])
            by_segment[segment] = by_segment[segment][take:]
            remaining_capacity -= take
            if remaining_capacity == 0:
                break
        confirmed_candidates = [due_date for candidates in by_segment.values() for due_date in candidates]

        selected_recontact = 0.0
        for attempt in sorted(recontact_available):
            take = min(recontact_available[attempt], recontact_capacity - selected_recontact)
            recontact_available[attempt] -= take
            selected_recontact += take
            if selected_recontact >= recontact_capacity:
                break
        recontact_available = Counter({attempt: count for attempt, count in recontact_available.items() if count > 0})

        selected_no_history = min(no_history_available, no_history_capacity)
        no_history_available -= selected_no_history
        enrolled = len(selected_confirmed) + selected_recontact + selected_no_history
        expected_bookings = enrolled * args.conversion_rate
        total_expected_bookings += expected_bookings
        recontact_schedule[week + args.sequence_plus_cooldown_weeks][1] += len(selected_confirmed) * (1 - args.conversion_rate) + selected_no_history * (1 - args.conversion_rate)
        # Re-contact failures return as a higher-attempt candidate after cooldown.
        recontact_schedule[week + args.sequence_plus_cooldown_weeks][2] += selected_recontact * (1 - args.conversion_rate)

        segment_counts = Counter(segment_for(due_date, simulation_date) for due_date in confirmed_candidates)
        projection_rows.append({
            "week": week,
            "simulation_date": simulation_date.isoformat(),
            "confirmed_enrolled": len(selected_confirmed),
            "recontact_enrolled": round(selected_recontact, 2),
            "no_history_enrolled": round(selected_no_history, 2),
            "expected_bookings": round(expected_bookings, 2),
            "hot_backlog": segment_counts["hot"],
            "warm_backlog": segment_counts["warm"],
            "cold_backlog": segment_counts["cold"],
            "very_cold_backlog": segment_counts["very_cold"],
            "confirmed_backlog_total": sum(segment_counts.values()),
            "recontact_available": round(sum(recontact_available.values()), 2),
            "no_history_available": round(no_history_available, 2),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=projection_rows[0].keys())
        writer.writeheader()
        writer.writerows(projection_rows)

    print(f"As of date: {args.as_of_date.isoformat()}")
    print(f"Initial confirmed backlog: {initial_confirmed_backlog:,}")
    print(f"Historical newly-overdue inflow: {weekly_inflow:.1f}/week")
    print(f"Weekly enrollment ceiling: {args.weekly_capacity:.0f}")
    print(f"Expected bookings over {args.weeks} weeks: {total_expected_bookings:.0f}")
    print(f"Week {args.weeks} confirmed backlog: {projection_rows[-1]['confirmed_backlog_total']:,}")
    print(f"Wrote projection: {args.output}")


if __name__ == "__main__":
    main()
