"""Measure age patterns across sequential patient-ID cohorts.

This diagnostic reports aggregate statistics only. It is intended to assess
whether patient ID provides enough signal to justify imputing missing birth
dates; it does not write any imputed values.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze age by sequential patient-ID cohort."
    )
    parser.add_argument("--patients", required=True, type=Path)
    parser.add_argument(
        "--as-of-date",
        type=date.fromisoformat,
        default=datetime.now().date(),
        help="Date used to calculate age (defaults to the date the script runs).",
    )
    parser.add_argument("--bucket-size", type=int, default=1_000)
    return parser.parse_args()


def age_on(birth_date: date, as_of_date: date) -> int:
    return as_of_date.year - birth_date.year - (
        (as_of_date.month, as_of_date.day) < (birth_date.month, birth_date.day)
    )


def pearson_correlation(pairs: list[tuple[int, int]]) -> float:
    x_values, y_values = zip(*pairs)
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in pairs)
    x_sum_squares = sum((x - x_mean) ** 2 for x in x_values)
    y_sum_squares = sum((y - y_mean) ** 2 for y in y_values)
    return numerator / math.sqrt(x_sum_squares * y_sum_squares)


def main() -> None:
    args = parse_args()
    if not args.patients.is_file():
        raise FileNotFoundError(f"CSV file not found: {args.patients}")

    buckets: dict[int, list[int]] = defaultdict(list)
    id_age_pairs: list[tuple[int, int]] = []
    missing_by_bucket: dict[int, int] = defaultdict(int)

    with args.patients.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            patient_id = int(row["patient_id"].rsplit("-", maxsplit=1)[-1])
            bucket = (patient_id - 1) // args.bucket_size
            birth_date_value = (row.get("birth_date") or "").strip()

            if not birth_date_value:
                missing_by_bucket[bucket] += 1
                continue

            patient_age = age_on(
                datetime.strptime(birth_date_value, "%Y-%m-%d").date(),
                args.as_of_date,
            )
            buckets[bucket].append(patient_age)
            id_age_pairs.append((patient_id, patient_age))

    print(f"Age by patient-ID cohort as of {args.as_of_date.isoformat()}")
    print(
        f"{'Patient IDs':<15} {'Known ages':>11} {'Missing DOB':>12} "
        f"{'Mean age':>10} {'Median age':>12} {'Min–max':>12}"
    )
    print("-" * 82)
    for bucket in sorted(set(buckets) | set(missing_by_bucket)):
        start = bucket * args.bucket_size + 1
        end = (bucket + 1) * args.bucket_size
        ages = buckets[bucket]
        age_range = f"{min(ages)}–{max(ages)}" if ages else "n/a"
        print(
            f"{start:05d}-{end:05d} {len(ages):>11,} {missing_by_bucket[bucket]:>12,} "
            f"{statistics.fmean(ages):>10.1f} {statistics.median(ages):>12.1f} {age_range:>12}"
        )

    correlation = pearson_correlation(id_age_pairs)
    print(f"\nPearson correlation: patient ID vs. age = {correlation:.3f}")
    print(
        "Interpretation: a correlation near 0 indicates patient ID is not a "
        "useful age predictor; it should not be used to impute missing birth dates."
    )


if __name__ == "__main__":
    main()
