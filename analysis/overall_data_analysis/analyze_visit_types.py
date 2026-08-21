"""Profile synthetic visit types against the supplied canonical categories."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize visit_type and visit_category relationships."
    )
    parser.add_argument("--appointments", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.appointments.is_file():
        raise FileNotFoundError(f"CSV file not found: {args.appointments}")

    category_counts = Counter()
    type_counts = Counter()
    type_categories: dict[str, Counter[str]] = defaultdict(Counter)

    with args.appointments.open("r", encoding="utf-8-sig", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            visit_type = row["visit_type"].strip()
            category = row["visit_category"].strip()
            category_counts[category] += 1
            type_counts[visit_type] += 1
            type_categories[visit_type][category] += 1

    total = sum(category_counts.values())
    print(f"Appointments analyzed: {total:,}")
    print(f"Unique visit types: {len(type_counts)}")
    print(f"Unique visit categories: {len(category_counts)}")

    print("\nCanonical visit categories")
    for category, count in category_counts.most_common():
        print(f"  {category:<12} {count:>7,} ({count / total * 100:>5.2f}%)")

    print("\nSynthetic visit-type mapping")
    print(f"{'Visit type':<28} {'Appointments':>13} {'Mapped category / categories':<35}")
    print("-" * 80)
    for visit_type, count in type_counts.most_common():
        mapping = ", ".join(
            f"{category} ({category_count:,})"
            for category, category_count in type_categories[visit_type].most_common()
        )
        print(f"{visit_type:<28} {count:>13,} {mapping:<35}")

    multi_category_types = {
        visit_type: categories
        for visit_type, categories in type_categories.items()
        if len(categories) > 1
    }
    print(f"\nVisit types spanning multiple categories: {len(multi_category_types)}")
    if multi_category_types:
        for visit_type, categories in sorted(multi_category_types.items()):
            mapping = ", ".join(f"{name} ({count:,})" for name, count in categories.items())
            print(f"  {visit_type}: {mapping}")


if __name__ == "__main__":
    main()
