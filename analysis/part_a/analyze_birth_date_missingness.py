"""Check whether missing birth dates cluster in the patient roster.

The script reports aggregate distributions only; it never prints patient-level
records from the supplied anonymized export.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


GROUPING_COLUMNS = ("gender", "provider", "status", "is_active")


def normalized(value: str | None) -> str:
    return value.strip() if value and value.strip() else "<missing>"


def is_missing(value: str | None) -> bool:
    return value is None or not value.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare patients with missing versus present birth dates."
    )
    parser.add_argument("--patients", required=True, type=Path)
    return parser.parse_args()


def print_distribution(column: str, groups: dict[str, Counter[str]]) -> None:
    print(f"\n{column}")
    print(f"{'Value':<26} {'Birth date present':>19} {'Birth date missing':>19} {'Missing rate':>14}")
    print("-" * 82)

    values = sorted(set(groups["present"]) | set(groups["missing"]))
    for value in values:
        present = groups["present"][value]
        missing = groups["missing"][value]
        total = present + missing
        missing_rate = missing / total * 100 if total else 0
        print(f"{value:<26} {present:>19,} {missing:>19,} {missing_rate:>13.2f}%")


def main() -> None:
    args = parse_args()
    if not args.patients.is_file():
        raise FileNotFoundError(f"CSV file not found: {args.patients}")

    distributions: dict[str, dict[str, Counter[str]]] = {
        column: {"present": Counter(), "missing": Counter()}
        for column in GROUPING_COLUMNS
    }
    id_buckets: dict[str, Counter[str]] = {"present": Counter(), "missing": Counter()}
    total = Counter()

    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            birth_date_state = "missing" if is_missing(row.get("birth_date")) else "present"
            total[birth_date_state] += 1

            for column in GROUPING_COLUMNS:
                distributions[column][birth_date_state][normalized(row.get(column))] += 1

            patient_id = normalized(row.get("patient_id"))
            # Patient IDs are sequential-looking (e.g. PT-00001). Deciles help
            # detect whether missing dates are concentrated in one import era.
            numeric_id = int(patient_id.rsplit("-", maxsplit=1)[-1])
            id_buckets[birth_date_state][f"{(numeric_id - 1) // 1_000 * 1_000 + 1:05d}-{((numeric_id - 1) // 1_000 + 1) * 1_000:05d}"] += 1

    total_rows = total["present"] + total["missing"]
    print("Birth-date completeness")
    print(f"Total patients: {total_rows:,}")
    print(f"Present: {total['present']:,} ({total['present'] / total_rows * 100:.2f}%)")
    print(f"Missing: {total['missing']:,} ({total['missing'] / total_rows * 100:.2f}%)")

    for column in GROUPING_COLUMNS:
        print_distribution(column, distributions[column])

    print_distribution("patient_id range (1,000-ID buckets)", id_buckets)


if __name__ == "__main__":
    main()
