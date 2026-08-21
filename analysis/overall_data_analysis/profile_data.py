"""Profile recall-outreach CSV exports without modifying their contents.

Example:
    python analysis/overall_data_analysis/profile_data.py \
      --patients "recall-outreach-project 2/data/patients.csv" \
      --appointments "recall-outreach-project 2/data/appointments.csv"
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def is_missing(value: str | None) -> bool:
    """Treat empty and whitespace-only CSV values as missing."""
    return value is None or not value.strip()


def profile_csv(path: Path) -> tuple[int, list[str], Counter[str]]:
    """Return row count, column names, and missing-value counts by column."""
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ValueError(f"{path} has no header row.")

        columns = reader.fieldnames
        missing = Counter({column: 0 for column in columns})
        row_count = 0

        for row in reader:
            row_count += 1
            for column in columns:
                if is_missing(row.get(column)):
                    missing[column] += 1

    return row_count, columns, missing


def print_profile(label: str, path: Path) -> None:
    row_count, columns, missing = profile_csv(path)

    print(f"\n{label}: {path}")
    print(f"Rows: {row_count:,}")
    print(f"Columns: {len(columns)}")
    print(f"{'Column':<28} {'Missing':>10} {'Missing %':>11}")
    print("-" * 52)

    for column in columns:
        missing_count = missing[column]
        missing_percent = (missing_count / row_count * 100) if row_count else 0
        print(f"{column:<28} {missing_count:>10,} {missing_percent:>10.2f}%")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report null/blank values for recall outreach CSV files."
    )
    parser.add_argument("--patients", type=Path, required=True)
    parser.add_argument("--appointments", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for label, path in (("Patients", args.patients), ("Appointments", args.appointments)):
        if not path.is_file():
            raise FileNotFoundError(f"CSV file not found: {path}")
        print_profile(label, path)


if __name__ == "__main__":
    main()
