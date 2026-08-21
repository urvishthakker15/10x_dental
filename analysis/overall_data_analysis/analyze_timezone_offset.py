"""Infer the practice's UTC offset behavior from UTC and wall-clock fields."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare UTC appointment times with practice wall-clock times."
    )
    parser.add_argument("--appointments", required=True, type=Path)
    return parser.parse_args()


def format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{remainder:02d}"


def main() -> None:
    args = parse_args()
    if not args.appointments.is_file():
        raise FileNotFoundError(f"CSV file not found: {args.appointments}")

    offsets = Counter()
    offsets_by_year = defaultdict(Counter)
    mismatched_durations = 0
    los_angeles_wall_matches = 0
    total = 0

    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            utc_start = datetime.fromisoformat(row["start_time"])
            utc_end = datetime.fromisoformat(row["end_time"])
            wall_start = datetime.fromisoformat(row["wall_start_time"])
            wall_end = datetime.fromisoformat(row["wall_end_time"])

            # `wall_*` carries a +00:00 suffix in the export despite holding
            # local clock time. The difference therefore reveals UTC - local.
            utc_minus_local_minutes = round((utc_start - wall_start).total_seconds() / 60)
            local_utc_offset_minutes = -utc_minus_local_minutes
            offsets[local_utc_offset_minutes] += 1
            offsets_by_year[utc_start.year][local_utc_offset_minutes] += 1
            total += 1

            if (utc_end - utc_start) != (wall_end - wall_start):
                mismatched_durations += 1

            candidate_local = utc_start.astimezone(ZoneInfo("America/Los_Angeles"))
            if candidate_local.replace(tzinfo=None) == wall_start.replace(tzinfo=None):
                los_angeles_wall_matches += 1

    print(f"Appointments analyzed: {total:,}")
    print("\nInferred local UTC offsets")
    for offset, count in sorted(offsets.items()):
        print(f"  {format_offset(offset)}: {count:,} ({count / total * 100:.2f}%)")

    print("\nOffsets by appointment year")
    for year in sorted(offsets_by_year):
        summary = ", ".join(
            f"{format_offset(offset)}: {count:,}"
            for offset, count in sorted(offsets_by_year[year].items())
        )
        print(f"  {year}: {summary}")

    print(f"\nUTC/wall duration mismatches: {mismatched_durations:,}")
    print(
        "America/Los_Angeles wall-clock matches: "
        f"{los_angeles_wall_matches:,}/{total:,} "
        f"({los_angeles_wall_matches / total * 100:.2f}%)"
    )
    print(
        "\nInterpretation: UTC-08:00 in winter and UTC-07:00 in summer is "
        "consistent with North American Pacific Time (for example, "
        "America/Los_Angeles), but timestamps alone cannot uniquely prove the "
        "practice's exact IANA timezone."
    )


if __name__ == "__main__":
    main()
